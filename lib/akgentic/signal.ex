defmodule Akgentic.Signal do
  @moduledoc """
  Lightweight signal struct for agent communication.

  Provides a Jido.Signal-compatible data structure that can be used
  independently for testing and core logic. When Jido is available,
  signals can be created via `Jido.Signal.new!/3` for full CloudEvents
  compliance.

  ## Fields

    * `:id` - Unique signal identifier (auto-generated UUID)
    * `:type` - Signal type string (e.g., "akgentic.user_message")
    * `:source` - Signal origin identifier (e.g., "/agent/echo-1")
    * `:data` - Signal payload as a map
    * `:time` - Signal creation timestamp

  ## Examples

      signal = Akgentic.Signal.new("echo", %{content: "Hello!"}, source: "/agent/echo-1")
      signal.type
      # => "echo"
      signal.data.content
      # => "Hello!"
  """

  @type t :: %__MODULE__{
          id: String.t(),
          type: String.t(),
          source: String.t(),
          data: map(),
          time: DateTime.t()
        }

  @enforce_keys [:type, :source, :data]
  defstruct [
    :id,
    :type,
    :source,
    :data,
    :time
  ]

  @doc """
  Create a new signal.

  ## Options

    * `:source` - Signal source identifier (default: "/system")
    * `:id` - Custom signal ID (default: auto-generated UUID)

  ## Examples

      signal = Akgentic.Signal.new("echo", %{content: "Hello!"})
      signal = Akgentic.Signal.new("echo", %{content: "Hello!"}, source: "/agent/echo-1")
  """
  @spec new(String.t(), map(), keyword()) :: t()
  def new(type, data \\ %{}, opts \\ []) do
    source = Keyword.get(opts, :source, "/system")
    id = Keyword.get(opts, :id, generate_id())

    %__MODULE__{
      id: id,
      type: type,
      source: source,
      data: data,
      time: DateTime.utc_now()
    }
  end

  defp generate_id do
    :crypto.strong_rand_bytes(16)
    |> Base.encode16(case: :lower)
    |> then(fn hex ->
      <<a::binary-size(8), b::binary-size(4), c::binary-size(4), d::binary-size(4),
        e::binary-size(12)>> = hex

      "#{a}-#{b}-#{c}-#{d}-#{e}"
    end)
  end
end
