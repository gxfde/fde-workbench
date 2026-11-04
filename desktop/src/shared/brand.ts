/**
 * 品牌与产品名的唯一来源（server + desktop 双侧共享）。
 *
 * 红线①（AGENTS.md）：任何界面、窗口标题、提交文案里不硬编码产品名——
 * 改名只改这一个文件（桌面端）与 `fde_api.config.Settings.fde_product_name`
 * （服务端单点，见 server/.env FDE_PRODUCT_NAME 覆写口径）。
 *
 * 改名口径：
 *   - 产品全名（正式）：`蔡工FDE智能交付系统`——对外、窗口标题、登录页主标题
 *   - 品牌短名（空间紧的场合）：`蔡工FDE`——侧边栏品牌区、图标旁
 *   - 副标题（说明品类）：`智能交付系统`——侧边栏品牌副标题位
 */

/** 产品全名：正式名称，用于窗口标题、登录页主标题等显著位置。 */
export const PRODUCT_NAME = "蔡工FDE智能交付系统"

/** 品牌短名：侧边栏等横向空间受限的位置。 */
export const BRAND_NAME = "蔡工FDE"

/** 副标题：说明产品品类。 */
export const BRAND_SUBTITLE = "智能交付系统"

/** 登录时的设备标签：用于在后台会话列表里辨认本机客户端。 */
export const DEVICE_LABEL = `${PRODUCT_NAME} 桌面端`
