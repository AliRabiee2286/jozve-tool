"""Small in-process pub/sub bus used by the command-line run."""

EVENT_NAMES = (
    'run_started',
    'file_started',
    'stage_started',
    'stage_progress',
    'stage_finished',
    'warning',
    'error',
    'file_done',
    'run_finished',
)


class EventBus:
    """Publish dictionaries to listeners registered for named run events."""

    def __init__(self):
        self._listeners = {name: [] for name in EVENT_NAMES}

    def subscribe(self, name, callback):
        if name not in self._listeners:
            raise ValueError(f'Unknown event: {name}')
        if not callable(callback):
            raise TypeError('Event listener must be callable')
        if callback not in self._listeners[name]:
            self._listeners[name].append(callback)
        return callback

    on = subscribe

    def unsubscribe(self, name, callback):
        if name not in self._listeners:
            raise ValueError(f'Unknown event: {name}')
        try:
            self._listeners[name].remove(callback)
        except ValueError:
            return False
        return True

    off = unsubscribe

    def emit(self, name, payload=None, **fields):
        if name not in self._listeners:
            raise ValueError(f'Unknown event: {name}')
        if payload is None:
            data = {}
        elif isinstance(payload, dict):
            data = dict(payload)
        else:
            raise TypeError('Event payload must be a dictionary')
        data.update(fields)
        for callback in tuple(self._listeners[name]):
            callback(dict(data))
        return data
