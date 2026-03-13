defmodule Akgentic.Timer do
  @moduledoc """
  Inactivity timeout management for the Orchestrator.

  Tracks active tasks and triggers a timeout callback after a configurable
  delay when the orchestrator becomes idle (task_count reaches 0).

  Maps from the Python `Timer` class to an Elixir GenServer process.

  ## Python → Elixir Mapping

  | Python `Timer`        | Elixir `Akgentic.Timer`          |
  |-----------------------|----------------------------------|
  | `Timer(delay, cb)`    | `Timer.start_link(delay, cb)`    |
  | `timer.start()`       | `Timer.start_countdown/1`        |
  | `timer.cancel()`      | `Timer.cancel/1`                 |
  | `timer.task_started()`| `Timer.task_started/1`           |
  | `timer.task_completed()`| `Timer.task_completed/1`       |
  | `timer.task_count`    | `Timer.get_task_count/1`         |

  ## Examples

      {:ok, timer} = Akgentic.Timer.start_link(delay: 60, on_timeout: fn -> IO.puts("Timeout!") end)
      Akgentic.Timer.start_countdown(timer)
      Akgentic.Timer.task_started(timer)    # pauses countdown
      Akgentic.Timer.task_completed(timer)  # restarts countdown
      Akgentic.Timer.cancel(timer)          # prevents callback from firing
  """

  use GenServer

  require Logger

  defstruct [:delay, :on_timeout, :timer_ref, task_count: 0]

  @type t :: %__MODULE__{
          delay: pos_integer(),
          on_timeout: (-> any()),
          timer_ref: reference() | nil,
          task_count: non_neg_integer()
        }

  # --- Public API ---

  @doc """
  Start the timer process.

  ## Options

    * `:delay` - Seconds of inactivity before timeout (required)
    * `:on_timeout` - Zero-argument function invoked on timeout (required)
    * `:name` - Optional GenServer name for registration
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts) do
    delay = Keyword.fetch!(opts, :delay)
    on_timeout = Keyword.fetch!(opts, :on_timeout)
    name = Keyword.get(opts, :name, nil)

    gen_opts = if name, do: [name: name], else: []

    GenServer.start_link(__MODULE__, %__MODULE__{delay: delay, on_timeout: on_timeout}, gen_opts)
  end

  @doc """
  Start or restart the countdown timer.
  """
  @spec start_countdown(GenServer.server()) :: :ok
  def start_countdown(server) do
    GenServer.cast(server, :start_countdown)
  end

  @doc """
  Cancel the current timer, preventing the callback from firing.
  """
  @spec cancel(GenServer.server()) :: :ok
  def cancel(server) do
    GenServer.cast(server, :cancel)
  end

  @doc """
  Increment task count and cancel timer while tasks are active.
  """
  @spec task_started(GenServer.server()) :: :ok
  def task_started(server) do
    GenServer.cast(server, :task_started)
  end

  @doc """
  Decrement task count and restart timer when orchestrator becomes idle.
  """
  @spec task_completed(GenServer.server()) :: :ok
  def task_completed(server) do
    GenServer.cast(server, :task_completed)
  end

  @doc """
  Get the current task count.
  """
  @spec get_task_count(GenServer.server()) :: non_neg_integer()
  def get_task_count(server) do
    GenServer.call(server, :get_task_count)
  end

  @doc """
  Get the timer delay in seconds.
  """
  @spec get_delay(GenServer.server()) :: pos_integer()
  def get_delay(server) do
    GenServer.call(server, :get_delay)
  end

  # --- GenServer Callbacks ---

  @impl true
  def init(state) do
    {:ok, state}
  end

  @impl true
  def handle_cast(:start_countdown, state) do
    {:noreply, do_start_countdown(state)}
  end

  @impl true
  def handle_cast(:cancel, state) do
    {:noreply, do_cancel(state)}
  end

  @impl true
  def handle_cast(:task_started, state) do
    new_count = state.task_count + 1
    new_state = %{state | task_count: new_count}

    new_state =
      if new_count > 0 do
        do_cancel(new_state)
      else
        new_state
      end

    {:noreply, new_state}
  end

  @impl true
  def handle_cast(:task_completed, state) do
    new_count = max(state.task_count - 1, 0)
    new_state = %{state | task_count: new_count}

    new_state =
      if new_count <= 0 do
        do_start_countdown(new_state)
      else
        new_state
      end

    {:noreply, new_state}
  end

  @impl true
  def handle_call(:get_task_count, _from, state) do
    {:reply, state.task_count, state}
  end

  @impl true
  def handle_call(:get_delay, _from, state) do
    {:reply, state.delay, state}
  end

  @impl true
  def handle_info(:timeout_fired, state) do
    Logger.info("Timer timeout after #{state.delay}s inactivity")

    try do
      state.on_timeout.()
    rescue
      e ->
        Logger.error("Timer callback failed: #{inspect(e)}")
    end

    {:noreply, %{state | timer_ref: nil}}
  end

  # --- Private Helpers ---

  defp do_start_countdown(state) do
    state = do_cancel(state)
    ref = Process.send_after(self(), :timeout_fired, state.delay * 1_000)
    %{state | timer_ref: ref}
  end

  defp do_cancel(%{timer_ref: nil} = state), do: state

  defp do_cancel(%{timer_ref: ref} = state) do
    Process.cancel_timer(ref)
    %{state | timer_ref: nil}
  end
end
