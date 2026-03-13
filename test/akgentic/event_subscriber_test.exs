defmodule Akgentic.EventSubscriberTest do
  use ExUnit.Case, async: true

  alias Akgentic.EventSubscriber

  describe "invoke_on_stop/1" do
    test "calls on_stop function in map-based subscriber" do
      test_pid = self()
      subscriber = %{on_stop: fn -> send(test_pid, :stopped) end}

      EventSubscriber.invoke_on_stop(subscriber)

      assert_receive :stopped
    end

    test "returns :ok for unknown subscriber types" do
      assert EventSubscriber.invoke_on_stop(%{}) == :ok
    end
  end

  describe "invoke_on_message/2" do
    test "calls on_message function in map-based subscriber" do
      test_pid = self()
      subscriber = %{on_message: fn signal -> send(test_pid, {:event, signal}) end}

      signal = %{type: "test.event", data: %{}}
      EventSubscriber.invoke_on_message(subscriber, signal)

      assert_receive {:event, ^signal}
    end

    test "returns :ok for unknown subscriber types" do
      assert EventSubscriber.invoke_on_message(%{}, %{}) == :ok
    end
  end

  describe "module-based subscriber" do
    defmodule TestModuleSubscriber do
      @behaviour Akgentic.EventSubscriber

      @impl true
      def on_stop, do: :ok

      @impl true
      def on_message(_signal), do: :ok
    end

    test "module implements the behaviour" do
      assert EventSubscriber.invoke_on_stop(TestModuleSubscriber) == :ok
      assert EventSubscriber.invoke_on_message(TestModuleSubscriber, %{}) == :ok
    end
  end
end
