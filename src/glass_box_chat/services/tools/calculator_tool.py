from __future__ import annotations

import ast
import math

from .tool_gateway import BaseTool, ToolInput, ToolOutput


class SafeMathEvaluator:
    """Safely evaluate mathematical expressions."""
    
    ALLOWED_NAMES = {
        "pi": math.pi,
        "e": math.e,
        "sqrt": math.sqrt,
        "pow": math.pow,
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "ceil": math.ceil,
        "floor": math.floor,
    }
    
    ALLOWED_OPERATORS = {
        ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, 
        ast.Pow, ast.USub, ast.UAdd
    }
    
    @staticmethod
    def evaluate(expression: str) -> str:
        """
        Safely evaluate a mathematical expression.
        
        Returns the result as a string.
        Supports: +, -, *, /, //, %, **, math functions
        """
        # Clean expression
        expr = expression.strip().replace("^", "**")
        
        # Basic validation
        if not expr:
            return "Error: Empty expression"
        
        # Check for dangerous patterns
        if any(pattern in expr for pattern in ["__", "import", "exec", "eval", "open", "file"]):
            return "Error: forbidden patterns in expression"
        
        try:
            # Parse the expression
            tree = ast.parse(expr, mode="eval")
            
            # Validate the AST
            if not SafeMathEvaluator._is_safe_node(tree.body):
                return "Error: expression contains unsafe operations"
            
            # Compile and evaluate
            code = compile(tree, "<string>", "eval")
            result = eval(code, {"__builtins__": {}}, SafeMathEvaluator.ALLOWED_NAMES)
            
            # Format result
            if isinstance(result, float):
                # Round to reasonable precision
                if result == int(result):
                    return str(int(result))
                else:
                    # Show up to 10 significant digits
                    return f"{result:.10g}"
            else:
                return str(result)
        
        except ZeroDivisionError:
            return "Error: Division by zero"
        except ValueError as e:
            return f"Error: Invalid value - {str(e)}"
        except Exception as e:
            return f"Error: Invalid expression - {str(e)}"
    
    @staticmethod
    def _is_safe_node(node: ast.expr) -> bool:
        """Check if AST node contains only safe operations."""
        if isinstance(node, ast.Constant):
            return True
        elif isinstance(node, ast.Name):
            return node.id in SafeMathEvaluator.ALLOWED_NAMES
        elif isinstance(node, ast.BinOp):
            return (type(node.op) in SafeMathEvaluator.ALLOWED_OPERATORS and
                   SafeMathEvaluator._is_safe_node(node.left) and
                   SafeMathEvaluator._is_safe_node(node.right))
        elif isinstance(node, ast.UnaryOp):
            return (type(node.op) in SafeMathEvaluator.ALLOWED_OPERATORS and
                   SafeMathEvaluator._is_safe_node(node.operand))
        elif isinstance(node, ast.Call):
            return (isinstance(node.func, ast.Name) and
                   node.func.id in SafeMathEvaluator.ALLOWED_NAMES and
                   all(SafeMathEvaluator._is_safe_node(arg) for arg in node.args))
        else:
            return False


class CalculatorTool(BaseTool):
    """Mathematical expression calculator."""
    
    def __init__(self) -> None:
        super().__init__(
            name="calculator",
            description="Calculate mathematical expressions. Supports +, -, *, /, %, ^, sqrt, sin, cos, log, etc.",
            timeout_seconds=2.0,
            max_retries=0,  # No retry for calculations
        )
    
    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        """Execute calculation and return result."""
        expression = tool_input.query.strip()
        
        if not expression:
            return ToolOutput(
                success=False,
                content="Error: No expression provided",
                confidence=0.0,
            )
        
        # Evaluate
        result = SafeMathEvaluator.evaluate(expression)
        
        is_error = result.startswith("Error:")
        if is_error:
            return ToolOutput(
                success=False,
                content=result,
                confidence=0.0,
            )
        
        content = f"Calculation Result\n\nExpression: {expression}\nResult: {result}"
        
        return ToolOutput(
            success=True,
            content=content,
            data={
                "expression": expression,
                "result": result,
            },
            confidence=0.95,  # High confidence for deterministic calculations
            metadata={
                "calculator": "SafeMathEvaluator",
                "source": "calculator",
                "expression_type": "math",
            },
        )
