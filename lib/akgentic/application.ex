defmodule Akgentic.Application do
  @moduledoc """
  OTP Application for Akgentic.

  Starts the supervision tree including the DynamicSupervisor
  for managing agent processes.
  """
  use Application

  @impl true
  def start(_type, _args) do
    children = [
      {DynamicSupervisor, name: Akgentic.AgentSupervisor, strategy: :one_for_one},
      {Registry, keys: :unique, name: Akgentic.AgentRegistry}
    ]

    opts = [strategy: :one_for_one, name: Akgentic.Supervisor]
    Supervisor.start_link(children, opts)
  end
end
