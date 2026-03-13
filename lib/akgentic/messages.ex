defmodule Akgentic.Messages do
  @moduledoc """
  Message types for agent communication.

  In the Jido architecture, messages are represented as signals following the
  CloudEvents specification. This module provides helper functions for creating
  common signal types used in Akgentic.

  ## Python → Elixir Mapping

  | Python `Message`     | Elixir `Akgentic.Signal`          |
  |----------------------|-----------------------------------|
  | `Message.id`         | `signal.id`                       |
  | `Message.parent_id`  | Signal correlation via `subject`  |
  | `Message.team_id`    | Signal data extensions            |
  | `Message.timestamp`  | `signal.time`                     |
  | `Message.sender`     | `signal.source`                   |
  | `UserMessage`        | Signal type `"user_message"`      |
  | `ResultMessage`      | Signal type `"result_message"`    |

  ## Examples

      signal = Akgentic.Messages.user_message("Hello!", source: "/user/1")
      signal = Akgentic.Messages.result_message("Response text", source: "/agent/echo-1")
  """

  alias Akgentic.Signal

  @doc """
  Create a user message signal.

  ## Options

    * `:source` - Signal source identifier (default: "/user")
    * `:subject` - Signal subject for routing (optional)

  ## Examples

      signal = Akgentic.Messages.user_message("Hello, agent!")
  """
  @spec user_message(String.t(), keyword()) :: Signal.t()
  def user_message(content, opts \\ []) do
    source = Keyword.get(opts, :source, "/user")

    data = %{content: content, display_type: "human"}

    Signal.new("akgentic.user_message", data, source: source)
  end

  @doc """
  Create a result/AI response message signal.

  ## Options

    * `:source` - Signal source identifier (default: "/agent")

  ## Examples

      signal = Akgentic.Messages.result_message("Here is the answer.")
  """
  @spec result_message(String.t(), keyword()) :: Signal.t()
  def result_message(content, opts \\ []) do
    source = Keyword.get(opts, :source, "/agent")

    data = %{content: content, display_type: "ai"}

    Signal.new("akgentic.result_message", data, source: source)
  end

  @doc """
  Create a generic message signal.

  ## Options

    * `:source` - Signal source identifier (default: "/system")

  ## Examples

      signal = Akgentic.Messages.new("custom.event", %{key: "value"})
  """
  @spec new(String.t(), map(), keyword()) :: Signal.t()
  def new(type, data \\ %{}, opts \\ []) do
    source = Keyword.get(opts, :source, "/system")
    Signal.new(type, data, source: source)
  end
end
