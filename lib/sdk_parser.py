"""Formatting helpers for logging Claude SDK responses."""


def log_response(label: str, response) -> None:
    """Print a labelled summary of a messages.create response."""
    print(f"\n{'=' * 60}")
    print(f"  {label}")
    print(f"{'=' * 60}")
    print(f"  stop_reason : {response.stop_reason}")
    print(f"  model       : {response.model}")
    print(f"  usage       : {response.usage.input_tokens} in / {response.usage.output_tokens} out")
    print(f"  content blocks ({len(response.content)}):")
    for i, block in enumerate(response.content):
        print(f"    [{i}] type={block.type}", end="")
        if block.type == "text":
            preview = block.text[:80].replace("\n", " ")
            print(f'  text="{preview}{"..." if len(block.text) > 80 else ""}"')
        elif block.type == "tool_use":
            print(f"  id={block.id}  name={block.name}  input={block.input}")
        else:
            print()
    print(f"{'=' * 60}\n")


def log_tool_call(tool_name: str, tool_input: dict, tool_result) -> None:
    """Print a labelled record of a local tool execution."""
    print(f"  [tool_call] {tool_name}({tool_input}) => {tool_result}")
