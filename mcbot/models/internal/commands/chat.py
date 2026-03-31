import inspect
from typing import Callable, Any, Awaitable, TYPE_CHECKING

from mcbot.models.internal.commands import CallbackType, Command, CommandType

if TYPE_CHECKING:
    from mcbot import Context

class ChatCommand(Command):
    def __init__(self, name: str, callback: CallbackType, description: str = "", help: str = "", triggers: list[str] = []):
        self.name = name
        self.callback = callback
        self.description = description or callback.__doc__ or ""
        self.help = help
        self.triggers = triggers or [name, name[0]]
        self.cmd_type = CommandType.CHAT
    
    # TODO: use https://github.com/cj-vana/meshcore-community-bot to synchronize commands
    async def dispatch(self, ctx: Context, *args, **kwargs) -> Any:
        if ext := ctx.bot._extensions.get(self.callback.__qualname__.split(".")[0]):
            await self.callback(ext, ctx, *args, **kwargs)
        else:
            await self.callback(ctx, *args, **kwargs)
            
def chat_command(
    name: str = "",
    *,
    description: str = "",
    help: str = "",
    triggers: list[str] = [],
) -> Callable[[CallbackType], ChatCommand]:
    """Create a new chat command.
    
    Usage:
    ```
    bot = Bot(settings)
    
    @chat_command(description="Pong!", triggers=["ping", "p"])
    async def ping(ctx):
    await ctx.send("Pong!")
    ```
    
    Args:
        name: Name of the command
        description: Optional description of the command. 
            Defaults to the docstring (what you're reading now)
        help: Help string, i.e. `command args`
        triggers: List of text matches. 
            Defaults to the name and the first character of the name   
    """
    def wrapper(func: CallbackType) -> ChatCommand:
        if not inspect.iscoroutinefunction(func):
            raise ValueError("Commands must be coroutines!")
        
        _name = name or func.__name__
        _description = description or func.__doc__ or "No description"
        _help = help or _name
        _triggers = triggers
        
        cmd = ChatCommand(_name, func, _description, _help, _triggers)
        return cmd
    return wrapper