# Q1.2 数据探索发现

本报告借助ai进行对思考的总结，完整思考过程见(q1.2探索.ipynb)，具体内容经过人工核实与修改。ai整理过程中存在修改添加不实内容，经检查以删除。

本报告依据 [Q1.2 探索 Notebook](q1.2探索.ipynb) 已保存的运行结果。数据为 Online Retail II 的 `data/online_retail_ii.csv`，共有 **1,067,371 条明细**。本地字段 `Invoice`、`Price` 分别对应题目中的 `InvoiceNo`、`UnitPrice`。除特别注明外，金额为 `Quantity × Price` 的带符号合计，保留取消、负值及调整记录。

下面的支持代码按顺序使用同一个 `df`。读取时保留标识符的原始文本，只把 CSV 空字段记为缺失。

```python
from pathlib import Path
import pandas as pd

paths = [Path("data/online_retail_ii.csv"), Path("../data/online_retail_ii.csv")]
csv_path = next((path for path in paths if path.is_file()), None)
if csv_path is None:
    raise FileNotFoundError(f"找不到 Online Retail II CSV，当前目录为 {Path.cwd()}")

df = pd.read_csv(csv_path, dtype="string", keep_default_na=False, na_values=[""])
df["Quantity"] = pd.to_numeric(df["Quantity"], errors="raise")
df["Price"] = pd.to_numeric(df["Price"], errors="raise")
df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], format="ISO8601", errors="raise")
df["Invoice"] = df["Invoice"].str.strip()
df["StockCode"] = df["StockCode"].str.strip()
df["明细金额"] = df["Quantity"] * df["Price"]

invoice = df["Invoice"].str.upper()
is_cancel = invoice.str.startswith("C", na=False)
```

## 问题 1：发票号的字母前缀

全表有 **19,500 条非纯数字发票明细**。去掉首尾空白后，只发现 `C` 和 `A` 两种前缀。空发票号以及非纯数字但没有字母前缀的发票号均为 0 行。

| 前缀 | 明细行数 | 不同发票号数 | 业务解读与证据 |
|---|---:|---:|---|
| `C` | 19,494 | 8,292 | [UCI 字段说明](https://archive.ics.uci.edu/dataset/502/online%2Bretail%2Bii)将 `C` 开头定义为取消。以 `C581484` 为例，数量 −80,995、单价 2.08，符合以负数量冲回原销售的特征。前缀可识别取消单据，单据内是商品还是费用，仍需结合 `StockCode` 判断。 |
| `A` | 6 | 6 | 6 行全部为 `StockCode = B`、描述 `Adjust bad debt`、数量 1、客户 ID 缺失。5 行单价为负，`A563185` 的单价为正（11,062.06）。这批记录有一致的坏账调整标签，金额正负取决于明细。 |

**销售额口径。** 在商品下单总额中，将 `C` 类记录单列为取消，并按已识别的业务标签排除 `A` 类坏账调整。在需要反映取消影响的商品净额中，纳入属于商品的取消明细，保留其金额的正负号。坏账调整留在账务分析中，方便核对销售口径与全量金额的差额。

```python
present = invoice.notna() & invoice.ne("").fillna(False)
non_numeric = present & ~invoice.str.fullmatch(r"[0-9]+", na=False)
unusual = df.loc[non_numeric].copy()
unusual["前缀"] = invoice.loc[non_numeric].str.extract(r"^([A-Z]+)", expand=False)
unusual["负数量"] = unusual["Quantity"].lt(0)
unusual["负单价"] = unusual["Price"].lt(0)

print("空发票号行数", int((~present).sum()))
print("非纯数字发票号行数", len(unusual))
print(unusual.groupby("前缀", dropna=False).agg(
    明细行数=("Invoice", "size"), 不同发票号数=("Invoice", "nunique"),
    负数量行数=("负数量", "sum"), 负单价行数=("负单价", "sum"),
))
print(unusual.loc[unusual["前缀"].isin(["A"])].to_string(index=False))
```

## 问题 2：特殊格式的商品编码

按题目示例 `85123A`，把「数字 + 字母」定义为连续数字在前、连续英文字母在后。用 `[0-9]+[A-Za-z]*` 匹配整个编码，可以同时识别纯数字和这类编码。其余非空编码进入格式候选，`DCGS0003` 和 `gift_0001_40` 也包含在内。随后查阅 `Description`，再决定候选的业务类别。


### 已核实的业务标签

| 编码 | 含义 | 原始描述证据 |
|---|---|---|
| `POST` | 邮费 | 2,115 行 `POSTAGE`，另有 7 行缺描述且为零价。 |
| `DOT` | 网站邮费 | 1,444 行 `DOTCOM POSTAGE`，另有 2 行缺描述且为零价。 |
| `BANK CHARGES` | 银行费用 | 102 行均显示为 `Bank Charges`，在原始描述分组中分为 96 行和 6 行。 |
| `AMAZONFEE` | Amazon 相关费用 | 43 行均为 `AMAZON FEE`，具体收费类型未细分。 |
| `CRUK` | 原文标记的 CRUK 佣金 | 16 行均为 `CRUK Commission`，具体结算背景待核实。 |
| `D` | 折扣 | 177 行均为 `Discount`。 |
| `ADJUST` | 调整记录 | 67 行描述均以 `Adjustment by` 开头，调整原因待核实。 |
| `B` | 坏账调整 | 6 行均为 `Adjust bad debt`。 |
| `M`、`m` | 手工记录 | `M` 的 1,421 行和 `m` 的 5 行均为 `Manual`。相同的标签支持归到同一业务类别，具体记账目的仍待核实。 |
| `S` | 样品记录 | 104 行均为 `SAMPLES`。是否纳入销售要看报表口径。 |

### 商品证据与待核实编码

- `PADS` 的 19 行均为 `PADS TO MATCH ALL CUSHIONS`。`DCGSSBOY` 有 21 行 `BOYS PARTY BAG`，`DCGSSGIRL` 有 23 行 `GIRLS PARTY BAG`，两者各另有 2 行零价记录，分别标为 `update` 和缺描述。
- `DCGS0003` 有 14 行，其中 13 行描述为 `BOXED GLASS ASHTRAY`，数量和单价均为正。另 1 行描述为 `ebay`、数量 −7、单价 0。具体商品描述支持该编码用于商品明细，也说明同一编码下的其他记录仍需按行判断。
- `DCGSLBOY`、`DCGSLGIRL`、`GIFT` 各只有 1 条缺描述的零价记录。目前无法确认用途，此处假设其为商品代码

原题的 62 个候选全部列在下方。除上面已给证据的 18 个编码外，其余 44 个已确认符合**格式筛选**。`ADJUST2`、`TEST…` 和 `gift_…` 的拼写可以提供回查线索，但不能直接作为销售分类依据。

| 格式候选分组 | 编码 |
|---|---|
| 已识别特殊业务标签（11 个） | `POST`、`DOT`、`BANK CHARGES`、`AMAZONFEE`、`CRUK`、`D`、`ADJUST`、`B`、`M`、`m`、`S` |
| 已见具体商品描述（4 个） | `PADS`、`DCGSSBOY`、`DCGSSGIRL`、`DCGS0003` |
| 缺描述的单条记录（3 个） | `DCGSLBOY`、`DCGSLGIRL`、`GIFT` |
| 其他直连编码（6 个） | `C2`、`C3`、`ADJUST2`、`SP1002`、`TEST001`、`TEST002` |
| `gift_` 系列（9 个） | `gift_0001_10`、`gift_0001_20`、`gift_0001_30`、`gift_0001_40`、`gift_0001_50`、`gift_0001_60`、`gift_0001_70`、`gift_0001_80`、`gift_0001_90` |
| 其他 `DCGS` 系列（29 个） | `DCGS0004`、`DCGS0006`、`DCGS0016`、`DCGS0027`、`DCGS0036`、`DCGS0037`、`DCGS0039`、`DCGS0041`、`DCGS0044`、`DCGS0053`、`DCGS0055`、`DCGS0056`、`DCGS0057`、`DCGS0058`、`DCGS0059`、`DCGS0060`、`DCGS0062`、`DCGS0066N`、`DCGS0066P`、`DCGS0067`、`DCGS0068`、`DCGS0069`、`DCGS0070`、`DCGS0071`、`DCGS0072`、`DCGS0073`、`DCGS0074`、`DCGS0075`、`DCGS0076` |

以下代码分别输出三种口径。最后按候选编码及原始描述汇总，还可继续核对待分类项。

```python
stock = df["StockCode"]
has_code = stock.notna() & stock.ne("").fillna(False)
format_candidate = has_code & ~stock.str.fullmatch(r"[0-9]+[A-Za-z]*", na=False)
letters_only = stock.str.fullmatch(r"[A-Za-z]+(?:[ _]+[A-Za-z]+)*", na=False)
special_codes = {"POST", "DOT", "BANK CHARGES", "AMAZONFEE", "CRUK",
                 "D", "ADJUST", "B", "M", "m", "S"}
total_amount = df["明细金额"].sum()

for name, mask in {
    "题目格式候选": format_candidate,
    "字母类子集": letters_only,
    "已识别特殊业务编码": stock.isin(special_codes),
}.items():
    subset = df.loc[mask]
    amount = subset["明细金额"].sum()
    amount_share = amount / total_amount if total_amount else pd.NA
    print(name, subset["StockCode"].nunique(), len(subset),
          len(subset) / len(df), amount, amount_share)

print(df.loc[format_candidate].groupby(
    ["StockCode", "Description"], dropna=False
).agg(明细行数=("Invoice", "size"), 带符号金额=("明细金额", "sum")).to_string())
```

## 问题 3：数量极值与负单价

数量最大值和最小值各命中 1 行。两条记录的全部源字段如下。

| `Invoice` | `StockCode` | `Description` | `Quantity` | `InvoiceDate` | `Price` | `Customer ID` | `Country` |
|---|---|---|---:|---|---:|---|---|
| `581483` | `23843` | `PAPER CRAFT , LITTLE BIRDIE` | 80,995 | 2011-12-09 09:15:00 | 2.08 | `16446.0` | United Kingdom |
| `C581484` | `23843` | `PAPER CRAFT , LITTLE BIRDIE` | −80,995 | 2011-12-09 09:27:00 | 2.08 | `16446.0` | United Kingdom |

在全表中按同客户、同商品、数量相反、时间更早且发票不以 `C` 开头查找，**只有 1 条候选**，即 `581483`。单价相同，取消记录晚 12 分钟，两条明细金额分别为 168,469.60 和 −168,469.60。现有证据更符合一组销售及后续取消，因此保留两条记录。CSV 缺少显式原单引用，仍无法确认实际履约或最初录入数量是否准确。

`Price < 0` **共 5 行**，发票分别为 `A506401`、`A516228`、`A528059`、`A563186`、`A563187`。五条均使用编码 `B`，描述为 `Adjust bad debt`，数量为 1，客户 ID 为空，国家为 `United Kingdom`，带符号金额合计 **−158,676.14**。原始描述支持将它们归入坏账调整。在原始层保留，在商品销售报表中排除并单列。另有一条 `B` 记录的单价为正，所以 `B` 的 6 行与负单价的 5 行是不同口径。

**处理标准。** 极端值用于触发核查。结合发票前缀、描述和关联字段确定记录的业务用途，再决定各指标是否纳入。未经证实的录入错误先标记待核实，保留原始值及处理依据。

```python
minimum, maximum = df["Quantity"].min(), df["Quantity"].max()
source_fields = df.columns.drop("明细金额")
print(df.loc[df["Quantity"].isin([minimum, maximum]), source_fields].to_string(index=False))

for row in df.loc[df["Quantity"].eq(minimum) & is_cancel].to_dict("records"):
    if pd.isna(row["Customer ID"]) or pd.isna(row["StockCode"]) or pd.isna(row["InvoiceDate"]):
        continue
    original = df.loc[
        df["Customer ID"].eq(row["Customer ID"])
        & df["StockCode"].eq(row["StockCode"])
        & df["Quantity"].eq(-row["Quantity"])
        & df["InvoiceDate"].lt(row["InvoiceDate"])
        & ~is_cancel,
        source_fields,
    ].copy()
    original["单价相同"] = original["Price"].eq(row["Price"])
    original["距离取消时间"] = row["InvoiceDate"] - original["InvoiceDate"]
    print(row["Invoice"], "全表候选数", len(original))
    print(original.sort_values("距离取消时间").to_string(index=False))

negative_price = df.loc[df["Price"].lt(0)]
print(negative_price.to_string(index=False))
print("负单价明细数", len(negative_price), "带符号金额", negative_price["明细金额"].sum())
```

## 问题 4：缺失客户 ID 的记录有什么不同

### 行数与金额

全量明细中，有 **243,007 / 1,067,371 行**缺少客户 ID（**22.7669%**）。缺失组的带符号金额为 **2,638,958.18**，占全表带符号金额 **19,287,250.568** 的 **13.6824%**。金额占比比行数占比低 **9.0845 个百分点**。

将两组都换算为每百条明细后，缺失组带符号金额合计比非缺失组低约 **933.57**。其中正金额明细的贡献少了 **823.54**，约占每百行金额差距的 **88.2%**。两组的正金额明细占比接近（97.1663% 和 97.7176%），但平均每条正金额明细分别为 **13.68** 和 **22.03**。取消明细（每百行少 44.73）和负单价明细（每百行少 65.30）进一步扩大了差距。零金额明细在缺失组有 6,131 行（2.5230%），在非缺失组有 71 行（0.0086%）。这些零金额行计入组内总行数，金额贡献为零。

```python
missing_id = df["Customer ID"].isna()
group = missing_id.map({True: "ID 缺失", False: "ID 非缺失"})
amount = df["明细金额"]
row_share = missing_id.mean() * 100
amount_share = amount.loc[missing_id].sum() / amount.sum() * 100
print("缺失行数和行数占比", int(missing_id.sum()), row_share)
print("缺失组金额和金额占比", amount.loc[missing_id].sum(), amount_share)
print("金额占比减行数占比（百分点）", amount_share - row_share)

kind = pd.Series("其他负金额明细", index=df.index, dtype="string")
kind.loc[amount.gt(0)] = "正金额明细"
kind.loc[amount.eq(0)] = "零金额明细"
kind.loc[df["Price"].lt(0)] = "负单价明细"
kind.loc[is_cancel] = "C 开头的取消明细"
comparison = df.assign(客户组=group, 明细类型=kind).groupby(
    ["客户组", "明细类型"], as_index=False
).agg(明细行数=("Invoice", "size"), 金额合计=("明细金额", "sum"))
group_rows = comparison["客户组"].map(group.value_counts())
comparison["组内行数占比(%)"] = 100 * comparison["明细行数"] / group_rows
comparison["类别平均每行金额"] = comparison["金额合计"] / comparison["明细行数"]
comparison["每百行金额贡献"] = 100 * comparison["金额合计"] / group_rows
print(comparison.round(4).to_string(index=False))
```

### 国家分布

| 国家标签 | 缺失组行数 | 非缺失组行数 | 占缺失组行数 | 占非缺失组行数 | 该国明细 ID 缺失率 |
|---|---:|---:|---:|---:|---:|
| United Kingdom | 240,029 | 741,301 | 98.7745% | 89.9240% | 24.4596% |
| Germany | 0 | 17,624 | 0.0000% | 2.1379% | 0.0000% |
| France | 128 | 14,202 | 0.0527% | 1.7228% | 0.8932% |
| EIRE | 1,671 | 16,195 | 0.6876% | 1.9645% | 9.3530% |
| Hong Kong | 364 | 0 | 0.1498% | 0.0000% | 100.0000% |
| Bermuda | 34 | 0 | 0.0140% | 0.0000% | 100.0000% |

缺失组在英国的占比比非缺失组高 **8.8505 个百分点**。英国明细的缺失率为 24.4596%，非英国合计约 **3.46%**（2,978 / 86,041）。因此，按缺 ID 删行会改变数据的国家构成。例如香港和百慕大的原始明细会全部被删掉。这些数字按明细计，不能当成订单数或客户数。

```python
country = pd.crosstab(df["Country"].fillna("国家缺失"), group)
within_group = country.div(country.sum(axis=0), axis=1) * 100
country_report = country.add_suffix("行数").join(within_group.add_suffix("组内占比(%)"))
country_report["该国ID缺失率(%)"] = country["ID 缺失"] / country.sum(axis=1) * 100
country_report["组内占比差(百分点)"] = within_group["ID 缺失"] - within_group["ID 非缺失"]
print(country_report.sort_values("组内占比差(百分点)", key=lambda col: col.abs(),
                                 ascending=False).round(4).to_string())
```

### 客单价（按发票计算）

比较时排除 `C` 开头的发票，保留数量、单价均为正且发票号和商品编码非空的明细，并排除问题 2 的 11 个已标记特殊业务编码。再按发票号汇总，避免同一张发票被重复计数。筛选后没有混合缺失与非缺失 ID 的发票（**0 张**）。这里的金额是纳入的正向商品候选明细金额，折扣和邮费等已排除，不能用于还原实际付款。

| 客户组 | 发票数 | 平均每张发票金额 | 中位数 | P90 | 平均每张发票明细行数 |
|---|---:|---:|---:|---:|---:|
| ID 缺失 | 2,923 | 916.30 | 185.04 | 2,244.65 | 80.21 |
| ID 非缺失 | 36,613 | 476.56 | 304.80 | 842.88 | 21.93 |

缺失组平均每张发票金额更高，但中位数更低，P90 也明显更高。仅报均值会掩盖分布差异，缺失组较高的平均金额与高金额发票及更多明细行同时存在。前面比较的是每条明细的金额，这里比较一张发票内各行的合计，因此两者的排序可以不同。

```python
sales = df.loc[
    df["Invoice"].fillna("").ne("") & has_code & ~is_cancel
    & df["Quantity"].gt(0) & df["Price"].gt(0) & ~df["StockCode"].isin(special_codes)
].assign(ID缺失=missing_id)

orders = sales.groupby("Invoice").agg(
    发票金额=("明细金额", "sum"), 明细行数=("ID缺失", "size"), ID缺失行数=("ID缺失", "sum"),
)
mixed = orders["ID缺失行数"].gt(0) & orders["ID缺失行数"].lt(orders["明细行数"])
print("混合 ID 发票数", int(mixed.sum()))
orders = orders.loc[~mixed].copy()
orders["客户组"] = orders["ID缺失行数"].gt(0).map({True: "ID 缺失", False: "ID 非缺失"})
print(orders.groupby("客户组").agg(
    发票数=("发票金额", "size"), 均值=("发票金额", "mean"), 中位数=("发票金额", "median"),
    P90=("发票金额", lambda values: values.quantile(0.90)),
    平均每张发票明细行数=("明细行数", "mean"),
).round(2).to_string())
```

### 高频商品

沿用客单价的可比较发票。每张发票中的同一编码只计一次，覆盖率以各组的发票数为分母。以下为两组各自的前 10 个商品候选编码，括号中为组内发票覆盖率。

| 组内排名 | ID 缺失组 | ID 非缺失组 |
|---:|---|---|
| 1 | `85099B`（24.9401%） | `85123A`（13.3696%） |
| 2 | `21931`（21.0400%） | `22423`（9.0596%） |
| 3 | `21212`（20.8690%） | `85099B`（8.9039%） |
| 4 | `22423`（20.5611%） | `84879`（7.2433%） |
| 5 | `47566`（20.4242%） | `20725`（7.0439%） |
| 6 | `22197`（19.5005%） | `21212`（6.8500%） |
| 7 | `22379`（19.0558%） | `47566`（5.6728%） |
| 8 | `22355`（18.8505%） | `22383`（5.4735%） |
| 9 | `21232`（18.5426%） | `20727`（5.4543%） |
| 10 | `20724`（18.4742%） | `22382`（5.2413%） |

两组前 10 中有 **4 个**重合编码（`85099B`、`21212`、`22423`、`47566`）。例如 `85099B` 在缺失组覆盖 729 张发票，占 **24.9401%**，在非缺失组覆盖 3,260 张，占 **8.9039%**，相差 **16.0362 个百分点**。`84879` 则在非缺失组出现得更频繁（7.2433% 对 5.3028%）。这说明仅用有 ID 的发票会改变看到的高频商品排名。由于两组国家构成和平均每张发票的明细行数不同，目前的差距不能直接解释为买家偏好。

```python
items = sales[["Invoice", "StockCode"]].drop_duplicates().join(
    orders[["客户组"]], on="Invoice", how="inner"
)
products = items.groupby(["客户组", "StockCode"], as_index=False).agg(
    覆盖发票数=("Invoice", "size"),
).sort_values(["客户组", "覆盖发票数", "StockCode"], ascending=[True, False, True])
products["覆盖率(%)"] = 100 * products["覆盖发票数"] / products["客户组"].map(
    orders.groupby("客户组").size()
)
top = products.groupby("客户组").head(10)
print(top.round(4).to_string(index=False))
coverage = products.loc[products["StockCode"].isin(top["StockCode"])].pivot(
    index="StockCode", columns="客户组", values="覆盖率(%)"
).fillna(0)
coverage["缺失组减非缺失组(百分点)"] = coverage["ID 缺失"] - coverage["ID 非缺失"]
print(coverage.round(4).to_string())
print("两组 TOP 10 重合的编码数", int(top["StockCode"].value_counts().eq(2).sum()))
```

### 匿名记录可能来自什么人群

部分正向商品发票可能来自未关联账号的购买，例如游客结账，也可能来自未写入客户 ID 的渠道或导出流程。这些是待验证的解释。英国标签只能说明记录的国家归属，无法确认买家身份或账号状态。缺失组还包含坏账调整，因而不能把所有缺 ID 行当作匿名买家的交易。若要继续验证，可以限定英国的正向商品发票，按月份复核缺失率，并在相同国家和相近发票明细行数的范围内重比金额及商品覆盖率。确认买家或渠道仍需要账号状态、订单来源等额外字段。
