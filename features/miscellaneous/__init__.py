from typing import TYPE_CHECKING

from .miscellaneous import Miscellaneous

if TYPE_CHECKING:
    from tools.pumpumpal import pumpumpal


async def setup(bot: "pumpumpal"):
    await bot.add_cog(Miscellaneous(bot))
