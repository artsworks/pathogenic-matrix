extends Node

const MOD_DIR := "Artsworks-QoL"
const LOG_NAME := "Artsworks-QoL:Main"

# Script extensions to install, relative to this mod's folder, e.g. "extensions/scn/globals.gd".
const EXTENSIONS: Array[String] = []

var mod_dir_path := ""


func _init() -> void:
	mod_dir_path = ModLoaderMod.get_unpacked_dir().path_join(MOD_DIR)
	ModLoaderLog.info("Init", LOG_NAME)
	for rel_path in EXTENSIONS:
		ModLoaderMod.install_script_extension(mod_dir_path.path_join(rel_path))


func _ready() -> void:
	ModLoaderLog.info("Ready", LOG_NAME)
