import asyncio
import sys
import unittest

from mcp import Client, StdioServerParameters


class StdioTests(unittest.TestCase):
    def test_server_launches_and_lists_tools(self):
        async def check():
            parameters = StdioServerParameters(
                command=sys.executable, args=["-m", "cad_to_print_mcp.server"]
            )
            async with Client(parameters) as client:
                result = await client.list_tools()
                names = {tool.name for tool in result.tools}
                self.assertIn("prepare_print_job", names)
                self.assertIn("get_printer_status", names)

        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
