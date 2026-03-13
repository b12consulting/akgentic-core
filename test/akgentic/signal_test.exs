defmodule Akgentic.SignalTest do
  use ExUnit.Case, async: true

  alias Akgentic.Signal

  describe "new/3" do
    test "creates a signal with required fields" do
      signal = Signal.new("test.echo", %{content: "Hello!"})

      assert signal.type == "test.echo"
      assert signal.data == %{content: "Hello!"}
      assert signal.source == "/system"
      assert is_binary(signal.id)
      assert %DateTime{} = signal.time
    end

    test "accepts custom source" do
      signal = Signal.new("test.echo", %{}, source: "/agent/echo-1")

      assert signal.source == "/agent/echo-1"
    end

    test "accepts custom id" do
      signal = Signal.new("test.echo", %{}, id: "custom-id")

      assert signal.id == "custom-id"
    end

    test "generates unique IDs" do
      signal1 = Signal.new("test", %{})
      signal2 = Signal.new("test", %{})

      assert signal1.id != signal2.id
    end

    test "creates signals with empty data" do
      signal = Signal.new("test.ping")

      assert signal.type == "test.ping"
      assert signal.data == %{}
    end
  end
end
