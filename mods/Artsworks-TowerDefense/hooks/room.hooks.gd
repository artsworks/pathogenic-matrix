extends Object

const LOG_NAME := "Artsworks-TowerDefense:RoomHooks"


func _ready(chain: ModLoaderHookChain) -> void:
	chain.execute_next()
	ModLoaderLog.info("Room ready: %s" % chain.reference_object.name, LOG_NAME)
