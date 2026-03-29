from typing import Any


class ToolResolver:
    def __init__(self) -> None:
        self._tool_instances: dict[str, object] = {}

    def resolve(self, selected_tool: object | None) -> object | None:
        if selected_tool is None:
            return None

        if hasattr(selected_tool, "execute") and hasattr(selected_tool, "name"):
            return selected_tool

        if not isinstance(selected_tool, str):
            return None

        tool_name = selected_tool.strip().lower()
        if not tool_name:
            return None

        cached = self._tool_instances.get(tool_name)
        if cached is not None:
            return cached

        try:
            from .calculator_tool import CalculatorTool
            from .fetch_page_tool import FetchPageTool
            from .finance_tool import FinanceTool
            from .news_api_tool import NewsAPITool
            from .weather_tool import WeatherTool
            from .web_search_tool import WebSearchTool
        except Exception:
            return None

        factories = {
            "web_search": WebSearchTool,
            "weather": WeatherTool,
            "news_api": NewsAPITool,
            "fetch_page": FetchPageTool,
            "calculator": CalculatorTool,
            "finance": FinanceTool,
        }
        factory = factories.get(tool_name)
        if factory is None:
            return None

        instance = factory()
        self._tool_instances[tool_name] = instance
        return instance
