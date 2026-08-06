from datetime import datetime, time as dtime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from .alerting import apply_escalation_policy, current_oncall_group, dispatch_alert_notifications
from .models import (
    Alert,
    AlertNotificationChannel,
    AlertNotificationLog,
    AlertNotificationPolicy,
    AlertNotificationRoute,
    AlertRecipient,
    AlertRecipientGroup,
    AlertSource,
    OnCallSchedule,
    TransactionTicket,
)
from .serializers import TransactionTicketSerializer


def aware(year, month, day, hour=0, minute=0):
    return timezone.make_aware(datetime(year, month, day, hour, minute), timezone.get_current_timezone())


class OnCallScheduleParsingTests(TestCase):
    def create_schedule(self, weekday_bits=127, start=None, end=None, name='值班班次'):
        return OnCallSchedule.objects.create(
            name=name,
            recipient_group=self.group,
            weekday_bits=weekday_bits,
            start_time=start or dtime(9, 0),
            end_time=end or dtime(18, 0),
        )

    def setUp(self):
        self.group = AlertRecipientGroup.objects.create(name='值班组')

    def test_weekday_and_time_match(self):
        self.create_schedule(weekday_bits=4)  # 周三
        schedule = current_oncall_group(now=aware(2026, 8, 5, 10, 0))  # 2026-08-05 周三
        self.assertIsNotNone(schedule)
        self.assertEqual(schedule.name, '值班班次')

    def test_time_outside_schedule_returns_none(self):
        self.create_schedule(weekday_bits=4, start=dtime(9, 0), end=dtime(18, 0))
        self.assertIsNone(current_oncall_group(now=aware(2026, 8, 5, 20, 0)))

    def test_weekday_bits_filter(self):
        self.create_schedule(weekday_bits=2)  # 周二
        self.assertIsNone(current_oncall_group(now=aware(2026, 8, 5, 10, 0)))  # 周三

    def test_overnight_schedule(self):
        self.create_schedule(weekday_bits=4, start=dtime(23, 0), end=dtime(6, 0))
        self.assertIsNotNone(current_oncall_group(now=aware(2026, 8, 5, 2, 0)))  # 周三凌晨
        self.assertIsNone(current_oncall_group(now=aware(2026, 8, 5, 15, 0)))
        self.assertIsNotNone(current_oncall_group(now=aware(2026, 8, 5, 23, 30)))

    def test_multi_schedule_takes_min_id(self):
        first = self.create_schedule(start=dtime(0, 0), end=dtime(23, 59), name='全天一班')
        self.create_schedule(start=dtime(0, 0), end=dtime(23, 59), name='全天二班')
        schedule = current_oncall_group(now=aware(2026, 8, 5, 10, 0))
        self.assertEqual(schedule.id, first.id)

    def test_disabled_schedule_skipped(self):
        self.create_schedule()
        OnCallSchedule.objects.update(is_enabled=False)
        self.assertIsNone(current_oncall_group(now=aware(2026, 8, 5, 10, 0)))

    def test_no_schedule_returns_none(self):
        self.assertIsNone(current_oncall_group(now=aware(2026, 8, 5, 10, 0)))


class OnCallEscalationTests(TestCase):
    def setUp(self):
        self.base_recipient = AlertRecipient.objects.create(
            name='张三', phone='13800000000', preferred_channels=['voice'],
        )
        self.oncall_recipient = AlertRecipient.objects.create(
            name='值班人', phone='13900000000', preferred_channels=['voice'],
        )
        self.base_group = AlertRecipientGroup.objects.create(name='基础接收组')
        self.base_group.recipients.add(self.base_recipient)
        self.oncall_group = AlertRecipientGroup.objects.create(name='值班组')
        self.oncall_group.recipients.add(self.oncall_recipient)
        self.schedule = OnCallSchedule.objects.create(
            name='当班', recipient_group=self.oncall_group,
            weekday_bits=127, start_time=dtime(0, 0), end_time=dtime(23, 59, 59),
        )
        self.source = AlertSource.objects.create(name='Zabbix 源', provider=AlertSource.PROVIDER_ZABBIX)
        self.channel = AlertNotificationChannel.objects.create(
            name='语音渠道', channel_type='voice', config={},
        )

    def make_alert(self):
        return Alert.objects.create(
            title='磁盘满', level='warning', status=Alert.STATUS_ACTIVE,
            source=self.source.code, source_type=Alert.SOURCE_ZABBIX, alert_source=self.source,
            starts_at=timezone.now() - timedelta(minutes=6),
        )

    def capture_escalation(self, alert, policy, route):
        captured = {}

        def fake_send(channel, target_alert, contacts, **kwargs):
            captured.update({'contacts': contacts})
            return AlertNotificationLog.objects.create(
                alert=target_alert, policy_id=policy.id, channel_id=channel.id,
                action='escalation', status=AlertNotificationLog.STATUS_SUCCESS,
                request_payload=kwargs.get('notification_metadata') or {},
                sent_at=timezone.now(),
            )

        from unittest.mock import patch

        with patch('ops.alerting.send_alert_notification', side_effect=fake_send):
            apply_escalation_policy(alert)
        return captured.get('contacts', {})

    def test_escalation_includes_oncall_group(self):
        policy = AlertNotificationPolicy.objects.create(
            name='未认领升级', alert_source=self.source,
            oncall_schedule=self.schedule, group_wait_seconds=0,
        )
        AlertNotificationRoute.objects.create(
            policy=policy, level='warning', trigger=AlertNotificationRoute.TRIGGER_UNACKNOWLEDGED,
            after_minutes=1, channel=self.channel,
            target_type=AlertNotificationRoute.TARGET_RECIPIENT_GROUP, recipient_group=self.base_group,
        )
        contacts = self.capture_escalation(self.make_alert(), policy, None)
        self.assertEqual(contacts.get('voice_phones'), ['13800000000', '13900000000'])

    def test_fire_notification_unaffected_by_oncall(self):
        policy = AlertNotificationPolicy.objects.create(
            name='首次通知', alert_source=self.source,
            oncall_schedule=self.schedule, group_wait_seconds=0,
        )
        AlertNotificationRoute.objects.create(
            policy=policy, level='warning', trigger=AlertNotificationRoute.TRIGGER_IMMEDIATE,
            after_minutes=0, channel=self.channel,
            target_type=AlertNotificationRoute.TARGET_RECIPIENT_GROUP, recipient_group=self.base_group,
        )
        alert = self.make_alert()
        from unittest.mock import patch

        with patch('ops.alerting.send_alert_notification') as send:
            dispatch_alert_notifications(alert, action='fire', force=True)
        self.assertEqual(send.call_count, 1)
        contacts = send.call_args.args[2]
        self.assertEqual(contacts.get('voice_phones'), ['13800000000'])
        self.assertNotIn('13900000000', contacts.get('voice_phones', []))

    def test_no_current_schedule_falls_back(self):
        self.schedule.weekday_bits = 2  # 周二，今天不是
        self.schedule.save(update_fields=['weekday_bits'])
        policy = AlertNotificationPolicy.objects.create(
            name='未认领升级', alert_source=self.source,
            oncall_schedule=self.schedule, group_wait_seconds=0,
        )
        AlertNotificationRoute.objects.create(
            policy=policy, level='warning', trigger=AlertNotificationRoute.TRIGGER_UNACKNOWLEDGED,
            after_minutes=1, channel=self.channel,
            target_type=AlertNotificationRoute.TARGET_RECIPIENT_GROUP, recipient_group=self.base_group,
        )
        contacts = self.capture_escalation(self.make_alert(), policy, None)
        self.assertEqual(contacts.get('voice_phones'), ['13800000000'])

    def test_no_oncall_schedule_keeps_original_behavior(self):
        policy = AlertNotificationPolicy.objects.create(
            name='未认领升级', alert_source=self.source, group_wait_seconds=0,
        )
        AlertNotificationRoute.objects.create(
            policy=policy, level='warning', trigger=AlertNotificationRoute.TRIGGER_UNACKNOWLEDGED,
            after_minutes=1, channel=self.channel,
            target_type=AlertNotificationRoute.TARGET_RECIPIENT_GROUP, recipient_group=self.base_group,
        )
        contacts = self.capture_escalation(self.make_alert(), policy, None)
        self.assertEqual(contacts.get('voice_phones'), ['13800000000'])


class AlertTicketApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_superuser('ticket-admin', 'admin@example.com', 'Admin@123456')
        self.client.force_authenticate(user=self.user)
        self.recipient = AlertRecipient.objects.create(name='值班人', phone='13900000000')
        self.group = AlertRecipientGroup.objects.create(name='当班值班组')
        self.group.recipients.add(self.recipient)
        self.schedule = OnCallSchedule.objects.create(
            name='当班', recipient_group=self.group,
            weekday_bits=127, start_time=dtime(0, 0), end_time=dtime(23, 59, 59),
        )
        self.source = AlertSource.objects.create(name='Zabbix 源', provider=AlertSource.PROVIDER_ZABBIX)
        self.alert = Alert.objects.create(
            title='磁盘满', level='critical', status=Alert.STATUS_ACTIVE,
            source=self.source.code, source_type=Alert.SOURCE_ZABBIX, alert_source=self.source,
            labels={'instance': '10.0.0.1'}, resource='10.0.0.1',
            starts_at=timezone.now() - timedelta(minutes=6),
        )

    def test_create_ticket_uses_defaults_and_default_owner_from_oncall(self):
        response = self.client.post(f'/api/alerts/{self.alert.id}/create-ticket/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertTrue(data['created'])
        ticket = TransactionTicket.objects.get(id=data['id'])
        self.assertEqual(ticket.ticket_type, TransactionTicket.TYPE_INCIDENT)
        self.assertEqual(ticket.status, TransactionTicket.STATUS_PENDING)
        self.assertEqual(ticket.priority, TransactionTicket.PRIORITY_HIGH)  # critical -> high
        self.assertEqual(ticket.applicant, self.user.username)
        self.assertEqual(ticket.owner, '当班值班组')
        self.assertTrue(ticket.description)

    def test_create_ticket_is_idempotent(self):
        first = self.client.post(f'/api/alerts/{self.alert.id}/create-ticket/', {}, format='json').json()
        second = self.client.post(f'/api/alerts/{self.alert.id}/create-ticket/', {}, format='json').json()
        self.assertFalse(second['created'])
        self.assertEqual(second['id'], first['id'])
        self.assertEqual(TransactionTicket.objects.count(), 1)

    def test_create_ticket_reuses_processing_incident(self):
        first = self.client.post(f'/api/alerts/{self.alert.id}/create-ticket/', {}, format='json').json()
        TransactionTicket.objects.filter(id=first['id']).update(status=TransactionTicket.STATUS_PROCESSING)
        second = self.client.post(f'/api/alerts/{self.alert.id}/create-ticket/', {}, format='json').json()
        self.assertFalse(second['created'])
        self.assertEqual(second['id'], first['id'])

    def test_create_ticket_creates_duplicate_after_resolved(self):
        first = self.client.post(f'/api/alerts/{self.alert.id}/create-ticket/', {}, format='json').json()
        TransactionTicket.objects.filter(id=first['id']).update(status=TransactionTicket.STATUS_DONE)
        second = self.client.post(f'/api/alerts/{self.alert.id}/create-ticket/', {}, format='json').json()
        self.assertTrue(second['created'])
        self.assertNotEqual(second['id'], first['id'])

    def test_create_ticket_custom_priority_and_owner(self):
        response = self.client.post(
            f'/api/alerts/{self.alert.id}/create-ticket/',
            {'priority': 'low', 'owner': '张三', 'title': '自定义标题'}, format='json',
        )
        self.assertEqual(response.status_code, 200)
        ticket = TransactionTicket.objects.get(id=response.json()['id'])
        self.assertEqual(ticket.priority, TransactionTicket.PRIORITY_LOW)
        self.assertEqual(ticket.owner, '张三')
        self.assertEqual(ticket.title, '自定义标题')

    def test_tickets_list(self):
        self.client.post(f'/api/alerts/{self.alert.id}/create-ticket/', {}, format='json')
        response = self.client.get(f'/api/alerts/{self.alert.id}/tickets/')
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]['title'], '磁盘满')
        self.assertEqual(payload[0]['ticket_type'], 'incident')

    def test_ticket_serializer_includes_alerts(self):
        self.client.post(f'/api/alerts/{self.alert.id}/create-ticket/', {}, format='json')
        ticket = TransactionTicket.objects.get()
        data = TransactionTicketSerializer(ticket).data
        self.assertEqual(len(data['alerts']), 1)
        self.assertEqual(data['alerts'][0]['id'], self.alert.id)
        self.assertEqual(data['alerts'][0]['title'], '磁盘满')

    def test_create_ticket_requires_authentication(self):
        self.client.force_authenticate(user=None)
        response = self.client.post(f'/api/alerts/{self.alert.id}/create-ticket/', {}, format='json')
        self.assertEqual(response.status_code, 401)
