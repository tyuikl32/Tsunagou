# D189 控制台只监听回环，默认端口固定为 2812

日期：2026-10-01
状态：已实施

## 决定

1. 控制台（`tsunagou web start`）默认端口固定为 **2812**；被占用时另取一个空闲端口，并在启动时说明
   （manifest 里同时记 `port_requested` / `port_fallback`）。人**明确写下**的端口（`--port`，或配置文件
   里的 `port`）被占用时**不**回退，照实失败。
2. 控制台**只允许监听回环地址**（`127.x.x.x` / `::1` / `localhost`）；非回环直接拒绝启动。

## 为什么

- **固定端口是给人方便的**：地址稳定才谈得上把页面收藏下来。
- **占用就换**是为了不"为了占住一个端口而拒绝启动"（端口是稀缺资源）；但换了一定要说，
  否则人收藏的是一个过期地址。
- **显式端口不回退**：隧道与防火墙规则是对着它配的，静默换一个会看起来"启动成功"、实际谁也访问不到。
- **只允许回环是安全边界**：控制台**自身没有任何认证**，它拿着各项目的 `control.token` 替页面转发
  用户级命令（删项目、任命主 Agent 都经过它）。监听在回环之外，等于把"操作这台机器上所有项目"的权力
  交给网络。要把页面看到别的机器，用隧道（SSH 端口转发等）——那仍然只在本机开 socket。

## 影响

- 以前 `--host 0.0.0.0` 之类能起来；现在会被 `console_host_must_be_loopback:<host>` 拒绝。
- `.tsunagou-console.local.json` 多两个字段：`port_requested`、`port_fallback`。
- 端口默认值从"随机"变成 2812：同一台机器上第一个控制台会占住它，第二个实例自动退让。

## 落点

`console/config.py`（`DEFAULT_PORT`、`port_explicit`、`is_loopback_host`）、
`console/service.py`（`choose_port` 返回 `(port, moved)`、`serve()` 拒非回环、manifest 记录）、
`cli/app.py`（`--port` 标为显式、回退时多打印一行）、`tests/unit/test_console_service.py`、
`web/method.md`、`docs/implementation/cli-contract.md`。
