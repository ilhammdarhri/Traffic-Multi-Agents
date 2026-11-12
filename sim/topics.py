"""MQTT topic tree, QoS and retained flags (single source of truth).

Topic tree:
    traffic/{carrefour}/approach/{dir}/queue    measured queue length
    traffic/{carrefour}/signal/plan             green times for the next cycle
    traffic/{carrefour}/signal/etat             phase actually displayed
    traffic/{carrefour}/offset/{id}             offset proposed at a consensus iteration
    traffic/priority/request                    emergency vehicle / bus priority request
    sma/agent/{id}/statut                       online / offline (offline = Last Will)
"""

# --- Topic builders -------------------------------------------------------

def queue(carrefour, direction):
    return f"traffic/{carrefour}/approach/{direction}/queue"


def signal_plan(carrefour):
    return f"traffic/{carrefour}/signal/plan"


def signal_etat(carrefour):
    return f"traffic/{carrefour}/signal/etat"


def offset(carrefour, agent_id):
    return f"traffic/{carrefour}/offset/{agent_id}"


PRIORITY_REQUEST = "traffic/priority/request"


def agent_status(agent_id):
    return f"sma/agent/{agent_id}/statut"


# --- Subscription patterns (wildcards) ------------------------------------
ALL_QUEUES = "traffic/+/approach/+/queue"      # + = one level
ALL_OFFSETS = "traffic/+/offset/+"
ALL_STATUS = "sma/agent/+/statut"


def everything_of(carrefour):
    return f"traffic/{carrefour}/#"            # # = all levels below


# --- QoS and retained, per message kind -----------------------------------
# QoS 0: loss acceptable (a fresh measure arrives every second)
# QoS 1: must arrive, duplicates harmless (idempotent state)
# QoS 2: must arrive exactly once (a priority request must not be duplicated)
QOS = {
    "queue": 0,
    "plan": 1,
    "etat": 1,
    "offset": 1,
    "priority": 2,
    "status": 1,
}

RETAINED = {
    "queue": False,
    "plan": True,       # a late joiner needs the latest plan
    "etat": True,       # last known actuator state
    "offset": False,
    "priority": False,
    "status": True,     # current online/offline of each agent
}

STATUS_ONLINE = "online"
STATUS_OFFLINE = "offline"
