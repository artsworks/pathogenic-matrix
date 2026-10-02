extends "res://scn/level_generator.gd"

const LOG_NAME := "Artsworks-TowerDefense:LevelGenerator"


func _ready() -> void:
	super()
	ModLoaderLog.info("Level generator extended", LOG_NAME)
