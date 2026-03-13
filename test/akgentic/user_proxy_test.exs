defmodule Akgentic.UserProxyTest do
  use ExUnit.Case, async: true

  alias Akgentic.UserProxy

  describe "start_link/1" do
    test "starts the user proxy process" do
      {:ok, pid} = UserProxy.start_link(name: "test-proxy")
      assert Process.alive?(pid)
      GenServer.stop(pid)
    end
  end

  describe "receive_message/2" do
    test "stores messages in pending queue" do
      {:ok, pid} = UserProxy.start_link(name: "test-proxy")

      signal = %{
        type: "akgentic.user_message",
        source: "/agent/worker-1",
        data: %{content: "What should I do?"},
        id: "msg-1",
        time: DateTime.utc_now()
      }

      UserProxy.receive_message(pid, signal)
      Process.sleep(50)

      pending = UserProxy.get_pending_messages(pid)
      assert length(pending) == 1
      assert hd(pending).data.content == "What should I do?"

      GenServer.stop(pid)
    end

    test "calls message_handler callback when configured" do
      test_pid = self()

      {:ok, pid} =
        UserProxy.start_link(
          name: "test-proxy",
          message_handler: fn signal -> send(test_pid, {:received, signal}) end
        )

      signal = %{
        type: "akgentic.user_message",
        source: "/agent/worker-1",
        data: %{content: "Hello"},
        id: "msg-1",
        time: DateTime.utc_now()
      }

      UserProxy.receive_message(pid, signal)

      assert_receive {:received, ^signal}, 500

      GenServer.stop(pid)
    end
  end

  describe "clear_pending/1" do
    test "clears all pending messages" do
      {:ok, pid} = UserProxy.start_link(name: "test-proxy")

      signal = %{
        type: "akgentic.user_message",
        source: "/test",
        data: %{content: "msg"},
        id: "1",
        time: DateTime.utc_now()
      }

      UserProxy.receive_message(pid, signal)
      Process.sleep(50)

      assert length(UserProxy.get_pending_messages(pid)) == 1

      UserProxy.clear_pending(pid)
      Process.sleep(50)

      assert UserProxy.get_pending_messages(pid) == []

      GenServer.stop(pid)
    end
  end
end
