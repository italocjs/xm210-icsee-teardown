class InteractCmd extends RS485Base{
	// 协议的显示名称, 最好与文件名直接对应，不能超过16字符
	Name = "InteractCmd"

	// 指明该协议被哪些接口和功能实现，如果被多个接口支持，接口名以空格分隔
	Type = "COMM"

	CommandLen = 8

	HeadLen = 1

	// 命令头数据
	HeadData = [0xDD]

	// 地址码
	RS232Addr = 0xFF

	// 是否有弹起消息
	UpMsg = 0

	// 是否通过脚本解析：0：通明串口 1：脚本解析 2：外部解析
	ParseMode = 2
}

local cInteractCmd = InteractCmd();

return cInteractCmd;
