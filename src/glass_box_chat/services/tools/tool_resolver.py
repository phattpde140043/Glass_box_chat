class ToolResolver:
    """Resolves a tool name or tool-like object to a concrete tool instance.

    New tools can be registered at composition-root time via ``register()``.
    Factories may be any zero-argument callable (class or lambda), so callers
    can inject dependencies without modifying this class (OCP).
    """

    def __init__(self) -> None:
        self._tool_instances: dict[str, object] = {}
        self._factories: dict[str, object] = {}  # zero-arg callable -> instance
        self._register_defaults()

    def _register_defaults(self) -> None:
        try:
            from .calculator_tool import CalculatorTool
            from .fetch_page_tool import FetchPageTool
            from .finance_tool import FinanceTool
            from .local_search_tool import LocalSearchTool
            from .news_api_tool import NewsAPITool
            from .weather_tool import WeatherTool
            from .web_search_tool import WebSearchTool
        except Exception:
            return

        self._factories = {
            "web_search": WebSearchTool,
            "weather": WeatherTool,
            "news_api": NewsAPITool,
            "fetch_page": FetchPageTool,
            "calculator": CalculatorTool,
            "finance": FinanceTool,
            "local_search": LocalSearchTool,
        }

    def register(self, name: str, factory: object) -> None:
        """Register a custom tool factory (any zero-arg callable) by name.

        Passing a class is equivalent to the old behaviour.  Passing a lambda
        or any other callable lets callers inject dependencies at
        composition-root time without modifying this class.
        """
        self._factories[name.strip().lower()] = factory
        # Evict any cached instance so the new factory takes effect immediately.
        self._tool_instances.pop(name.strip().lower(), None)

    def resolve(self, selected_tool: object | None) -> object | None:
        if selected_tool is None:
            return None

        # Already a tool-like object — pass through directly.
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

        factory = self._factories.get(tool_name)
        if factory is None:
            return None

        instance = factory()
        self._tool_instances[tool_name] = instance
        return instance
