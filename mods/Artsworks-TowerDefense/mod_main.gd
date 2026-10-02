extends Node

const MOD_DIR := "Artsworks-TowerDefense"
const LOG_NAME := "Artsworks-TowerDefense:Main"

# Vanilla paths come from the demo build (docs/01-investigation.md) and are
# unconfirmed on the release build, so each install is skipped if the path is missing.
const LEVEL_GENERATOR_PATH := "res://scn/level_generator.gd"
const ROOM_PATH := "res://scn/environ/rooms/room.gd"

var mod_dir_path := ""


func _init() -> void:
	mod_dir_path = ModLoaderMod.get_unpacked_dir().path_join(MOD_DIR)
	ModLoaderLog.info("Init", LOG_NAME)
	_install_extension(LEVEL_GENERATOR_PATH, "extensions/level_generator.gd")
	_install_hooks(ROOM_PATH, "hooks/room.hooks.gd")


func _ready() -> void:
	ModLoaderLog.info("Ready", LOG_NAME)


func _install_extension(vanilla_path: String, rel_path: String) -> void:
	if not ResourceLoader.exists(vanilla_path):
		ModLoaderLog.info("Skipping extension, %s not found" % vanilla_path, LOG_NAME)
		return
	ModLoaderMod.install_script_extension(mod_dir_path.path_join(rel_path))


func _install_hooks(vanilla_path: String, rel_path: String) -> void:
	if not ResourceLoader.exists(vanilla_path):
		ModLoaderLog.info("Skipping hooks, %s not found" % vanilla_path, LOG_NAME)
		return
	ModLoaderMod.install_script_hooks(vanilla_path, mod_dir_path.path_join(rel_path))
