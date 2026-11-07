"""V3.2 FDE 交付模拟训练场（Delivery Simulation Lab）。

隔离边界（V3.2 G0 §2 / G1 §1.3）：
- 本包**不挂** ``projects.project_id``——模拟运行与真实项目在数据层就分开，
  从根上杜绝模拟数据混入真实项目视图、成本账本与证据口径。
- 与 V3.1 的唯一跨界是 ``simulation/adapters``：real 实现委托既有服务，
  mock 实现是**明确标记**的脚本化替身。包内任何模块不得直连 V3.1 内部字段。
- 场景内容分两侧装载（Tester View / Customer View / Judge View），参考答案
  只在 Judge View 可见——装载器是唯一入口，递归键断言防泄漏。
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
