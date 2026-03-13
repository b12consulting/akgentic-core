import Config

config :akgentic,
  orchestrator_timeout_delay: 3_600

import_config "#{config_env()}.exs"
