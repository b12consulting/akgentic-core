defmodule Akgentic.MessagesTest do
  use ExUnit.Case, async: true

  alias Akgentic.Messages

  describe "user_message/2" do
    test "creates a user message signal" do
      signal = Messages.user_message("Hello!")

      assert signal.type == "akgentic.user_message"
      assert signal.data.content == "Hello!"
      assert signal.data.display_type == "human"
      assert signal.source == "/user"
    end

    test "accepts custom source" do
      signal = Messages.user_message("Hello!", source: "/user/alice")

      assert signal.source == "/user/alice"
    end
  end

  describe "result_message/2" do
    test "creates a result message signal" do
      signal = Messages.result_message("Here is the answer.")

      assert signal.type == "akgentic.result_message"
      assert signal.data.content == "Here is the answer."
      assert signal.data.display_type == "ai"
      assert signal.source == "/agent"
    end
  end

  describe "new/3" do
    test "creates a generic signal" do
      signal = Messages.new("custom.event", %{key: "value"})

      assert signal.type == "custom.event"
      assert signal.data.key == "value"
      assert signal.source == "/system"
    end

    test "accepts custom source" do
      signal = Messages.new("custom.event", %{}, source: "/my-source")

      assert signal.source == "/my-source"
    end
  end
end
