defmodule Akgentic.Messages.Orchestrator do
  @moduledoc """
  Orchestrator telemetry message types.

  These signal types are used for tracking agent lifecycle events,
  message flows, and state changes. They map from the Python orchestrator
  message classes to signal types.

  ## Python → Elixir Mapping

  | Python Class           | Signal Type                           |
  |------------------------|---------------------------------------|
  | `StartMessage`         | `"akgentic.agent.started"`            |
  | `StopMessage`          | `"akgentic.agent.stopped"`            |
  | `SentMessage`          | `"akgentic.message.sent"`             |
  | `ReceivedMessage`      | `"akgentic.message.received"`         |
  | `ProcessedMessage`     | `"akgentic.message.processed"`        |
  | `ErrorMessage`         | `"akgentic.agent.error"`              |
  | `StateChangedMessage`  | `"akgentic.agent.state_changed"`      |
  | `EventMessage`         | `"akgentic.agent.event"`              |

  ## Examples

      signal = Akgentic.Messages.Orchestrator.agent_started("worker-1", %{name: "worker", role: "Worker"})
      signal = Akgentic.Messages.Orchestrator.agent_error("worker-1", "RuntimeError", "something failed")
  """

  alias Akgentic.Signal

  @type_prefix "akgentic"

  # Signal type constants
  @agent_started "#{@type_prefix}.agent.started"
  @agent_stopped "#{@type_prefix}.agent.stopped"
  @message_sent "#{@type_prefix}.message.sent"
  @message_received "#{@type_prefix}.message.received"
  @message_processed "#{@type_prefix}.message.processed"
  @agent_error "#{@type_prefix}.agent.error"
  @state_changed "#{@type_prefix}.agent.state_changed"
  @agent_event "#{@type_prefix}.agent.event"

  @doc "Returns the signal type for agent started events."
  def type_agent_started, do: @agent_started

  @doc "Returns the signal type for agent stopped events."
  def type_agent_stopped, do: @agent_stopped

  @doc "Returns the signal type for message sent events."
  def type_message_sent, do: @message_sent

  @doc "Returns the signal type for message received events."
  def type_message_received, do: @message_received

  @doc "Returns the signal type for message processed events."
  def type_message_processed, do: @message_processed

  @doc "Returns the signal type for agent error events."
  def type_agent_error, do: @agent_error

  @doc "Returns the signal type for state changed events."
  def type_state_changed, do: @state_changed

  @doc "Returns the signal type for agent event events."
  def type_agent_event, do: @agent_event

  @doc """
  Create an agent started signal.

  ## Parameters

    * `agent_id` - The ID of the agent that started
    * `config` - Agent configuration map (name, role, etc.)
    * `opts` - Additional signal options
  """
  @spec agent_started(String.t(), map(), keyword()) :: Signal.t()
  def agent_started(agent_id, config \\ %{}, opts \\ []) do
    source = Keyword.get(opts, :source, "/agent/#{agent_id}")
    parent = Keyword.get(opts, :parent, nil)

    data = %{
      agent_id: agent_id,
      config: config,
      parent: parent
    }

    Signal.new(@agent_started, data, source: source)
  end

  @doc """
  Create an agent stopped signal.
  """
  @spec agent_stopped(String.t(), keyword()) :: Signal.t()
  def agent_stopped(agent_id, opts \\ []) do
    source = Keyword.get(opts, :source, "/agent/#{agent_id}")
    Signal.new(@agent_stopped, %{agent_id: agent_id}, source: source)
  end

  @doc """
  Create a message sent telemetry signal.
  """
  @spec message_sent(String.t(), map(), String.t(), keyword()) :: Signal.t()
  def message_sent(sender_id, message, recipient_id, opts \\ []) do
    source = Keyword.get(opts, :source, "/agent/#{sender_id}")

    data = %{
      sender_id: sender_id,
      message: message,
      recipient_id: recipient_id
    }

    Signal.new(@message_sent, data, source: source)
  end

  @doc """
  Create a message received telemetry signal.
  """
  @spec message_received(String.t(), String.t(), keyword()) :: Signal.t()
  def message_received(agent_id, message_id, opts \\ []) do
    source = Keyword.get(opts, :source, "/agent/#{agent_id}")

    data = %{
      agent_id: agent_id,
      message_id: message_id
    }

    Signal.new(@message_received, data, source: source)
  end

  @doc """
  Create a message processed telemetry signal.
  """
  @spec message_processed(String.t(), String.t(), keyword()) :: Signal.t()
  def message_processed(agent_id, message_id, opts \\ []) do
    source = Keyword.get(opts, :source, "/agent/#{agent_id}")

    data = %{
      agent_id: agent_id,
      message_id: message_id
    }

    Signal.new(@message_processed, data, source: source)
  end

  @doc """
  Create an agent error telemetry signal.
  """
  @spec agent_error(String.t(), String.t(), String.t(), keyword()) :: Signal.t()
  def agent_error(agent_id, exception_type, exception_value, opts \\ []) do
    source = Keyword.get(opts, :source, "/agent/#{agent_id}")
    current_message = Keyword.get(opts, :current_message, nil)

    data = %{
      agent_id: agent_id,
      exception_type: exception_type,
      exception_value: exception_value,
      current_message: current_message
    }

    Signal.new(@agent_error, data, source: source)
  end

  @doc """
  Create a state changed telemetry signal.
  """
  @spec state_changed(String.t(), map(), keyword()) :: Signal.t()
  def state_changed(agent_id, state, opts \\ []) do
    source = Keyword.get(opts, :source, "/agent/#{agent_id}")

    data = %{
      agent_id: agent_id,
      state: state
    }

    Signal.new(@state_changed, data, source: source)
  end

  @doc """
  Create an agent event telemetry signal.
  """
  @spec agent_event(String.t(), term(), keyword()) :: Signal.t()
  def agent_event(agent_id, event, opts \\ []) do
    source = Keyword.get(opts, :source, "/agent/#{agent_id}")

    data = %{
      agent_id: agent_id,
      event: event
    }

    Signal.new(@agent_event, data, source: source)
  end
end
