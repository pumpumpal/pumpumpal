from typing import TYPE_CHECKING

from .fun import Fun

if TYPE_CHECKING:
    from tools.pumpumpal import pumpumpal


async def setup(bot: "pumpumpal"):
    await bot.add_cog(Fun(bot))
