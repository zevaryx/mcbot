import inspect
from typing import TYPE_CHECKING, Callable

from mcbot.models.internal.command import CallbackType

if TYPE_CHECKING:
    from mcbot.client import Bot
    from mcbot.models.internal.command import Command
    from mcbot.models.internal.task import Task

class Extension:
    name: str
    extension_name: str
    description: str
        
    _bot: Bot
    _commands: list[Command]
    _tasks: list[Task]
    
    def __new__(cls, bot: Bot, *args, **kwargs) -> Extension:
        instance = super().__new__(cls)
        instance._bot = bot
        instance.name = cls.__name__ # type: ignore
        
        if instance.name in bot._extensions:
            raise ValueError(f"An extension named {instance.name} is already loaded!")
        
        instance.extension_name = inspect.getmodule(instance).__name__ # type: ignore
        
        instance.description = kwargs.get("description", "")
        if not instance.description:
            instance.description = inspect.cleandoc(cls.__doc__) if cls.__doc__ else None # type: ignore
            
        instance._commands = []
        instance._tasks = []
        
        callables: list[tuple[str, Callable]] = inspect.getmembers(
            instance, predicate=lambda x: isinstance(x, (CallbackType, Task)) # type: ignore
        )
        
        for _name, val in callables:
            if isinstance(val, Command):
                bot.add_command(val)
                instance._commands.append(val)
                
            elif isinstance(val, Task):
                bot.task(val)
                instance._tasks.append(val)
                
        instance._bot._extensions[instance.name] = instance
        
        return instance
    
    @property
    def __name__(self) -> str:
        return self.name
    
    @property
    def bot(self) -> Bot:
        return self._bot
    
    @bot.setter
    def bot(self, value: Bot) -> None:
        self._bot = value
        
    @property
    def commands(self) -> list[Command]:
        return self._commands
    
    def drop(self) -> None:
        for func in self._commands:
            self._bot._commands.remove(func)
        for task in self._tasks:
            task.stop()
            self._bot._tasks.remove(task)
        self.bot._extensions.pop(self.name, None)
        self.bot._logger.debug(f"{self.name} has been dropped")