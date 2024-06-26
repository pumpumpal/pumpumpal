from typing import TYPE_CHECKING

from .webserver import Webserver

if TYPE_CHECKING:
    from tools.pumpumpal import pumpumpal


async def setup(bot: "pumpumpal"):
    await bot.add_cog(Webserver(bot))
