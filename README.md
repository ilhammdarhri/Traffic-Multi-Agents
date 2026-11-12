# Cooperative Traffic Signal Control at Connected Intersections

Multi-agent simulator: green-time sharing via consensus and game theory.
Module: Systemes Multi-Agents appliques a l'IoT (Master MSID S3).

## Structure

| Folder          | Content                                                   |
|-----------------|-----------------------------------------------------------|
| `agents/`       | Agent, UtilityAgent, IntersectionAgent, ApproachAgent...  |
| `kb/`           | Knowledge base (ontology .owl or rules .pl) + docs        |
| `coordination/` | Strategy interface: Selfish, Nash, Consensus, Centralized |
| `sim/`          | Queue simulator, MQTT client, sensors, actuators, runner  |
| `results/`      | CSV results and figures                                   |
| `tests/`        | Unit tests                                                |

## Quick start (to be completed)

1. Start the MQTT broker:
   `Start the MQTT broker (Mosquitto installed locally):
   `/usr/local/opt/mosquitto/sbin/mosquitto -c /usr/local/etc/mosquitto/mosquitto.conf -v`
   (macOS Intel with Homebrew; on Linux use `mosquitto -v`; alternative with Docker:
   `docker run -p 1883:1883 eclipse-mosquitto`)`
2. Install dependencies:
   `pip install -r requirements.txt`
3. Run the scenarios: TODO
4. Reproduce the figures: TODO

## Team

- Member 1: simulator, knowledge base
- Member 2: article, design dossier
