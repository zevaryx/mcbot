from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, Any, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from mcbot import Context

CallbackType = Callable[..., Awaitable[Any]]

class CommandType(Enum):
    PREFIXED = 0
    CHAT = 1

class Command(ABC):
    """Base command class with abstract methods"""
    name: str
    callback: CallbackType
    description: str
    help: str
    cmd_type: CommandType
    
    @abstractmethod
    async def dispatch(self, ctx: Context, *args, **kwargs) -> Any:
        """Dispatch the command
        
        Args:
            ctx: Command context
        """
        ...