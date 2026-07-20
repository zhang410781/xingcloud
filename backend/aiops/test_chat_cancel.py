from django.contrib.auth import get_user_model
from django.test import TestCase

from aiops.models import AIOpsChatMessage, AIOpsChatSession
from aiops.services import (
    PROCESSING_STATUS_CANCELLED,
    PROCESSING_STATUS_RUNNING,
    _update_chat_message_processing,
    cancel_chat_message_processing,
)


class ChatCancellationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser('chat-cancel-admin', 'cancel@example.com', 'test-password')
        self.session = AIOpsChatSession.objects.create(user=self.user, title='Cancel test')
        self.message = AIOpsChatMessage.objects.create(
            session=self.session,
            role=AIOpsChatMessage.ROLE_ASSISTANT,
            content='正在分析',
            metadata={'processing_status': 'running', 'processing_steps': []},
        )

    def test_cancel_endpoint_marks_message_terminal(self):
        self.client.force_login(self.user)
        response = self.client.post(f'/api/aiops/sessions/{self.session.id}/messages/{self.message.id}/cancel/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['metadata']['processing_status'], PROCESSING_STATUS_CANCELLED)

    def test_cancelled_message_cannot_be_overwritten_by_worker_updates(self):
        cancel_chat_message_processing(self.message, actor=self.user.username)
        _update_chat_message_processing(
            self.message.id,
            status_value=PROCESSING_STATUS_RUNNING,
            content='迟到的结果',
        )
        self.message.refresh_from_db()
        self.assertEqual(self.message.metadata['processing_status'], PROCESSING_STATUS_CANCELLED)
        self.assertNotEqual(self.message.content, '迟到的结果')
