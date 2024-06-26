from typing import TYPE_CHECKING

from .information import Information

if TYPE_CHECKING:
    from tools.pumpumpal import pumpumpal


async def setup(bot: "pumpumpal"):
    await bot.add_cog(Information(bot))
