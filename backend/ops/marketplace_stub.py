"""marketplace stub"""

class ServiceDeployment:
    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_RUNNING = 'running'

    id = 0

    @property
    def display_fields(self):
        return {}


class ServiceTemplate:
    id = 0
    name = ''

    @property
    def display_fields(self):
        return {}
