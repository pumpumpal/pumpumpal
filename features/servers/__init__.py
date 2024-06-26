from typing import TYPE_CHECKING

from .servers import Servers

if TYPE_CHECKING:
    from tools.pumpumpal import pumpumpal


async def setup(bot: "pumpumpal"):
    await bot.add_cog(Servers(bot))
