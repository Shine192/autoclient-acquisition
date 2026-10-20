#!/bin/zsh
cd "${0:A:h}"
python3 -m acquisition_agent.automatic_setup
read "shine_setup_done?Press Return to close."
