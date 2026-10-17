ALTER TABLE agent_runtime.model_attempts ADD COLUMN IF NOT EXISTS input_rate numeric NOT NULL DEFAULT 0.30;
ALTER TABLE agent_runtime.model_attempts ADD COLUMN IF NOT EXISTS output_rate numeric NOT NULL DEFAULT 1.20;
ALTER TABLE agent_runtime.model_attempts ADD COLUMN IF NOT EXISTS charged numeric;
