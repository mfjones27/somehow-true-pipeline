class FactoryError(Exception):
    status_code = 400
    code = "invalid_input"


class BusyError(FactoryError):
    status_code = 429
    code = "renderer_busy"


class DuplicateError(FactoryError):
    status_code = 409
    code = "duplicate_content_version"


class CapacityError(FactoryError):
    status_code = 507
    code = "local_capacity_exceeded"


class RenderError(FactoryError):
    status_code = 500
    code = "render_failed"

