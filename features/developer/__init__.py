from typing import TYPE_CHECKING

from .developer import Developer

if TYPE_CHECKING:
    from tools.pumpumpal import pumpumpal


async def setup(bot: "pumpumpal"):
    await bot.add_cog(Developer(bot))
