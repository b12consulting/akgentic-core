defmodule AkgenticTest do
  use ExUnit.Case, async: true

  describe "version/0" do
    test "returns the current version" do
      assert Akgentic.version() == "1.0.0-alpha.1"
    end
  end
end
