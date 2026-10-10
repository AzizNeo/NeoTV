"""Named architectural errors.

Every error in this file stops the application *at boot* and names the module
responsible. Nothing here is ever caught and silenced by the kernel: a puzzle
piece that does not fit must be reported, not skipped.
"""

from __future__ import annotations


class KernelError(RuntimeError):
    """Base class for boot-time architectural violations."""


class ModuleContractError(KernelError):
    def __init__(self, module: str, detail: str) -> None:
        super().__init__(f"[module:{module}] contract violation: {detail}")
        self.module = module
        self.detail = detail


class DuplicateModuleError(KernelError):
    pass


class UnknownModuleError(KernelError):
    """A name in DISABLED_MODULES does not match any installed module (typo guard)."""


class DuplicateCapabilityError(KernelError):
    def __init__(self, capability: str, first: str, second: str) -> None:
        super().__init__(f"capability '{capability}' is provided by both '{first}' and '{second}'")
        self.capability, self.first, self.second = capability, first, second


class MissingCapabilityError(KernelError):
    def __init__(self, module: str, capability: str) -> None:
        super().__init__(f"[module:{module}] requires '{capability}' but no installed module provides it")
        self.module, self.capability = module, capability


class DisabledDependencyError(KernelError):
    def __init__(self, module: str, capability: str, provider: str) -> None:
        super().__init__(f"[module:{module}] requires '{capability}' but its provider '{provider}' is DISABLED")
        self.module, self.capability, self.provider = module, capability, provider


class CircularModuleDependencyError(KernelError):
    pass


class DuplicateRouteError(KernelError):
    pass


class DuplicateScheduleError(KernelError):
    def __init__(self, schedule: str, owner: str) -> None:
        super().__init__(f"[module:{owner}] beat schedule '{schedule}' is already defined")


class HandlerImportError(KernelError):
    def __init__(self, module: str, path: str, cause: BaseException) -> None:
        super().__init__(f"[module:{module}] cannot import '{path}': {cause!r}")
        self.module, self.path = module, path
        self.__cause__ = cause


class UnknownExtensionPointError(KernelError):
    def __init__(self, module: str, point: str) -> None:
        super().__init__(
            f"[module:{module}] contributes to extension point '{point}' which no installed module declares"
        )


class DuplicateExtensionPointError(KernelError):
    def __init__(self, point: str, first: str, second: str) -> None:
        super().__init__(f"extension point '{point}' declared by both '{first}' and '{second}'")


class DuplicatePermissionError(KernelError):
    def __init__(self, permission: str, first: str, second: str) -> None:
        super().__init__(f"permission '{permission}' declared by both '{first}' and '{second}'")


class UnknownPermissionError(KernelError):
    pass
