"""
Demonstrates stop_reason values from the Claude SDK using a weather tool.

stop_reason == "tool_use"
  Claude decided to call a tool — the response contains a tool_use block.
  The loop must execute the tool and send the result back.

stop_reason == "end_turn"
  Claude has finished — no more tool calls, final answer is in the text block.
"""

# sys lets us modify Python's module search path at runtime
import sys
# os lets us read and write environment variables
import os

# Allow "from lib.sdk_parser import ..." to work when running this file directly,
# since lib/ lives one level up from this script's folder.
# os.path.dirname(__file__) = the folder this script is in (stop_reason/)
# ".." = one level up = the project root
# sys.path.insert(0, ...) = add the project root to the front of Python's search path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import urllib.request   # built-in HTTP client — no extra install needed
import urllib.parse     # used to URL-encode the city name (handles spaces, etc.)
import json             # parse the JSON response from wttr.in

# subprocess lets us run a terminal command from inside Python and capture its output
import subprocess
# anthropic is the official Python SDK for calling Claude
import anthropic
# load_dotenv reads key=value pairs from a .env file into environment variables
from dotenv import load_dotenv
# our own helper functions for printing formatted log output
from lib.sdk_parser import log_response, log_tool_call

# Read from .env file if present (fallback for non-DevBar environments)
load_dotenv()

# Run the DevBar command to get the gateway token from the OS keyring.
# subprocess.check_output() runs the command and returns its printed output as a string.
# text=True means return a string instead of raw bytes.
# .strip() removes the trailing newline character from the output.
token = subprocess.check_output(
    ["/Applications/devbar.app/Contents/MacOS/devbar", "auth", "claude"],
    text=True
).strip()

# Store the token in an environment variable — the Anthropic SDK reads this automatically
os.environ["ANTHROPIC_AUTH_TOKEN"] = token

# Point the SDK at Salesforce's internal AI gateway instead of api.anthropic.com directly.
# Without this, the token would be rejected since it only works through this proxy.
os.environ["ANTHROPIC_BASE_URL"] = "https://eng-ai-model-gateway.sfproxy.devx-preprod.aws-esvc1-useast2.aws.sfdc.cl"

# ---------------------------------------------------------------------------
# Tool definition
# ---------------------------------------------------------------------------
# This dict describes the tool to Claude.  Claude reads "name", "description",
# and "input_schema" to decide when and how to call the tool.
# It does NOT call the tool itself — we do that in the agentic loop below.
# ---------------------------------------------------------------------------

WEATHER_TOOL = {
    # The name Claude uses to refer to the tool when it wants to call it
    "name": "get_weather",
    # A plain English description — Claude reads this to know what the tool does
    "description": "Returns the current weather for a given city.",
    "input_schema": {
        # JSON Schema that describes what arguments Claude must supply
        "type": "object",
        "properties": {
            # Claude must pass a "city" argument as a string
            "city": {"type": "string", "description": "City name, e.g. 'Sydney'"},
        },
        # Claude must always include "city" — it is not optional
        "required": ["city"],
    },
}


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------
# This is the real Python function that runs locally when Claude asks for
# weather data.  It hits wttr.in — a free, public weather API that needs no
# API key.  It returns a plain string that we send back to Claude.
# ---------------------------------------------------------------------------

def get_weather(city: str) -> str:
    # URL-encode the city so "New York" becomes "New%20York" — required for a valid URL
    encoded = urllib.parse.quote(city)

    # Build the wttr.in URL. ?format=j1 returns structured JSON instead of an ASCII chart
    url = f"https://wttr.in/{encoded}?format=j1"

    # Create the HTTP request object with a User-Agent header.
    # wttr.in may reject requests that don't identify themselves with a User-Agent.
    req = urllib.request.Request(url, headers={"User-Agent": "weather-tool-demo/1.0"})

    # Open the URL, read the response body, and parse it from JSON into a Python dict.
    # "with" ensures the connection is closed automatically when done.
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())

    # Navigate the JSON structure to find the current conditions.
    # data["current_condition"] is a list — index [0] is the current reading.
    current = data["current_condition"][0]

    # Extract the specific fields we care about
    temp_c   = current["temp_C"]                    # temperature in Celsius
    desc     = current["weatherDesc"][0]["value"]   # e.g. "Partly cloudy"
    feels_c  = current["FeelsLikeC"]                # feels-like temperature
    humidity = current["humidity"]                  # humidity percentage

    # Return a single human-readable string — this is what Claude will see as the tool result
    return f"{desc}, {temp_c}°C (feels like {feels_c}°C), humidity {humidity}%"


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------
# The loop keeps sending messages to Claude until it stops calling tools.
# Each iteration:
#   1. Send the current message history to Claude
#   2. Check stop_reason on the response
#   3a. "tool_use"  → run the tool, append results, loop again
#   3b. "end_turn"  → Claude is done, print the final answer and exit
# ---------------------------------------------------------------------------

def run() -> None:
    # Create the Anthropic client.
    # It automatically reads ANTHROPIC_AUTH_TOKEN and ANTHROPIC_BASE_URL from the environment.
    # default_headers adds an extra header to every request — required by the Salesforce gateway.
    client = anthropic.Anthropic(
        default_headers={"x-sf-ai-harness-client-id": "claude"}
    )

    # messages is the conversation history — a list of turns, each with a role and content.
    # We start with a single user message asking about the weather.
    messages = [
        {"role": "user", "content": "What is the weather like in Sydney right now?"}
    ]

    print("User:", messages[0]["content"])

    # turn counts how many times we've called Claude — used only for logging
    turn = 0

    # Loop forever until we hit a break statement
    while True:
        turn += 1

        # Send the full message history to Claude, plus the list of tools it can use.
        # Claude will read all previous messages to understand the conversation context.
        response = client.messages.create(
            model="global.anthropic.claude-haiku-4-5-20251001-v1:0",
            max_tokens=1024,       # maximum number of tokens Claude can generate in its reply
            tools=[WEATHER_TOOL],  # the tools Claude is allowed to call
            messages=messages,     # the full conversation history so far
        )

        # Print a formatted summary of the raw response (stop_reason, blocks, token usage)
        log_response(f"Turn {turn} response", response)

        # ------------------------------------------------------------------
        # stop_reason == "tool_use"
        # Claude is not done yet — it wants to call a tool before answering.
        # We must: run the tool locally, then send the result back to Claude.
        # ------------------------------------------------------------------
        if response.stop_reason == "tool_use":

            # Save Claude's reply into the message history.
            # The API requires the assistant's tool_use request to appear in history
            # before we can send back the tool result.
            messages.append({"role": "assistant", "content": response.content})

            # Claude can request multiple tools in a single response — collect all results
            tool_results = []

            # Loop through every block in the response
            for block in response.content:
                # We only care about tool_use blocks — skip any text blocks
                if block.type == "tool_use":

                    # block.input is a dict like {"city": "Sydney"}.
                    # ** unpacks the dict into keyword arguments, so this becomes:
                    # get_weather(city="Sydney")
                    result = get_weather(**block.input)

                    # Log the tool call and result to the console for visibility
                    log_tool_call(block.name, block.input, result)

                    # Build the tool result object to send back to Claude.
                    # tool_use_id links this result back to the specific request Claude made —
                    # important when multiple tools are called at once.
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,  # must match the id from the tool_use block
                        "content": result,         # the string returned by get_weather()
                    })

            # Add the tool results to the conversation as a "user" turn.
            # This is the API's convention — tool results always come back as the "user" role.
            # Then "continue" jumps back to the top of the while loop to call Claude again.
            messages.append({"role": "user", "content": tool_results})
            continue

        # ------------------------------------------------------------------
        # stop_reason == "end_turn"
        # Claude has finished — it has all the information it needs and is
        # giving its final answer. No more tool calls.
        # ------------------------------------------------------------------
        if response.stop_reason == "end_turn":
            # Loop through the response blocks to find the text answer
            for block in response.content:
                # Only print text blocks — ignore anything else
                if block.type == "text":
                    print("Assistant:", block.text)
            # Exit the while loop — the conversation is complete
            break

        # If stop_reason is something unexpected (e.g. "max_tokens"), print it and stop.
        # This prevents an infinite loop if something goes wrong.
        print(f"Unexpected stop_reason: {response.stop_reason!r}")
        break


# Only call run() if this script is executed directly.
# If another file imports this script, run() will NOT be called automatically.
if __name__ == "__main__":
    run()
