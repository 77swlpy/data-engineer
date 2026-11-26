# -*- coding: utf-8 -*-
"""Q1.2 探索：由同名 Notebook 按单元格顺序导出。

保留原有探索代码与文字说明，文字说明以注释保存。
运行方式：python "q1_data_quality/q1.2探索.py"
"""

from pathlib import Path

import pandas as pd


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "online_retail_ii.csv"
if not DATA_PATH.is_file():
    raise FileNotFoundError(f"找不到数据文件：{DATA_PATH}")


def display(*objects):
    """将 Notebook 中的表格展示适配为终端文本输出。"""
    for obj in objects:
        if isinstance(obj, (pd.DataFrame, pd.Series)):
            print(obj.to_string())
        else:
            print(obj)
        print()

# %% [markdown]
# 原 Notebook 单元格 1
# **q1.2**

# %%
# 原 Notebook 单元格 2
from pathlib import Path
import pandas as pd

csv_path = DATA_PATH

# 保留原始文本，避免把订单号、商品编码或客户 ID 自动读成数字。
# 只把空字段识别为缺失，保留 CSV 里可能存在的字面值，如 "NA"。
raw = pd.read_csv(csv_path, dtype="string", keep_default_na=False, na_values=[""])

print("数据路径", csv_path.resolve())
print("行列数", raw.shape)
print("实际表头", raw.columns.tolist())
display(raw.head())

# %% [markdown]
# 原 Notebook 单元格 3
# **问题一**

# %%
# 原 Notebook 单元格 4
invoice_raw = raw["Invoice"]
invoice = invoice_raw.str.strip()

# 空值、空白发票号单独统计，不归入非纯数字发票号。
missing = invoice.isna() | invoice.eq("").fillna(False)
digits_only = invoice.str.fullmatch(r"[0-9]+", na=False)
non_numeric = invoice.loc[~missing & ~digits_only]

# 提取开头连续的英文字母，统一为大写后统计。
prefixes = non_numeric.str.extract(r"^([A-Za-z]+)", expand=False).str.upper()

prefix_report = (
    pd.DataFrame({"发票号": non_numeric, "前缀": prefixes})
    .dropna(subset=["前缀"])
    .groupby("前缀", as_index=False)
    .agg(
        出现次数=("发票号", "size"),
        不同发票号数=("发票号", "nunique"),
    )
    .sort_values(["出现次数", "前缀"], ascending=[False, True])
)

without_prefix = non_numeric.loc[prefixes.isna()]

print("空值或空白发票号行数", int(missing.sum()))
print("非纯数字发票号行数", len(non_numeric))
display(prefix_report)

print("非纯数字但没有字母前缀的行数", len(without_prefix))
if not without_prefix.empty:
    display(without_prefix.value_counts().rename("出现次数").to_frame())

# 确认所有非纯数字明细都进入了前缀统计或例外统计。
assert prefix_report["出现次数"].sum() + len(without_prefix) == len(non_numeric)

# %% [markdown]
# 原 Notebook 单元格 5
# 这个地方q1.1数据思考部分已经发现是什么问题了，这里仅作复制完善
#
# 首先C在数据集说明里面已经明确是代表已经取消的订单
#
# A代表坏账处理，具体如下

# %%
# 原 Notebook 单元格 6
# 按文本读取，保留发票号、商品编码和其他字段的原始表示。
raw = pd.read_csv(
    csv_path,
    dtype="string",
    keep_default_na=False,
    na_values=[""],
)

# 仅在筛选时忽略首尾空格和大小写，输出保留原始字段值。
starts_with_a = raw["Invoice"].str.strip().str.upper().str.startswith("A", na=False)
a_rows = raw.loc[starts_with_a]

print(f"A 开头的发票明细共 {len(a_rows):,} 行")
print(a_rows.to_string(index=False))

# %% [markdown]
# 原 Notebook 单元格 7
# 总结：
#
# 五条负单价明细都有坏账调整描述
#
# 全表筛选 Price < 0，共命中 **5 行**。这些行的发票号都以 A开头，StockCode 均为 B，描述均为 Adjust bad debt，数量均为 1，客户 ID 均为空。例如 A506401 的单价为 −53,594.36。
#
# 这种一致性支持将这五行识别为**坏账调整候选**。

# %% [markdown]
# 原 Notebook 单元格 8
# **问题二**

# %%
# 原 Notebook 单元格 9
#找出所有非纯数字、非"数字+字母"格式的 StockCode，统计这些记录占总行数和总金额的比例
# 只去掉首尾空格，保留代码内部的空格，例如 BANK CHARGES。
stock_code = raw["StockCode"].str.strip()
missing_code = stock_code.isna() | stock_code.eq("").fillna(False)

# 能匹配 22423、85123A 等形式。使用 fullmatch 检查整个编码。
is_standard_format = stock_code.str.fullmatch(r"[0-9]+[A-Za-z]*", na=False)
is_special_format = ~missing_code & ~is_standard_format

quantity = pd.to_numeric(raw["Quantity"], errors="raise")
price = pd.to_numeric(raw["Price"], errors="raise")

if quantity.isna().any() or price.isna().any():
    raise ValueError("数量或单价存在缺失，请先核查，再计算全表金额占比。")

# 全量口径保留金额正负号，包含取消及调整明细。
line_amount = quantity * price

total_rows = len(raw)
total_amount = line_amount.sum()
special_rows = int(is_special_format.sum())
special_amount = line_amount.loc[is_special_format].sum()

def percent(part, total):
    return 100 * part / total if total != 0 else pd.NA

summary = pd.DataFrame([{
    "全表行数": total_rows,
    "编码缺失或空白行数": int(missing_code.sum()),
    "特殊格式行数": special_rows,
    "特殊格式行数占比(%)": percent(special_rows, total_rows),
    "全表带符号金额": total_amount,
    "特殊格式带符号金额": special_amount,
    "特殊格式金额占比(%)": percent(special_amount, total_amount),
}])

# 按编码汇总，并打印所有命中编码。
by_code = (
    pd.DataFrame({
        "StockCode": stock_code.loc[is_special_format],
        "明细金额": line_amount.loc[is_special_format],
    })
    .groupby("StockCode", as_index=False)
    .agg(明细行数=("明细金额", "size"), 明细金额=("明细金额", "sum"))
    .sort_values(["明细行数", "StockCode"], ascending=[False, True])
)

display(summary.round(4))
print(f"符合筛选条件的不同编码共 {len(by_code)} 个")
print(by_code.round({"明细金额": 4}).to_string(index=False))

# %% [markdown]
# 原 Notebook 单元格 10
# 此处出现了一个问题，我将我的代码诉求交给ai后，ai给出的代码运行后出现了gift_0001_40这样的字段，我的理解是这个也属于数字加字母的组合，但是我详细询问ai后发现由于文档中举出的例子是以数字开头，ai把「数字 + 字母」理解为固定顺序：先连续数字，再连续字母，我认为这种字段在问题二中无意义，依旧代表的物品，但是如果题目真的想要筛选纯字母为什么要使用这种表达?此处需要确认字母加数字是否需要排除
#
# 2编：如果说纯字母会忽略字母与字母间用空格链接的情况

# %%
# 原 Notebook 单元格 11
# 如果前一格读取 CSV 时只选了三列，这里补读 Description 和 Invoice。
details = pd.read_csv(
    csv_path,
    usecols=["Invoice", "StockCode", "Description", "Quantity", "Price"],
    dtype="string",
    keep_default_na=False,
    na_values=[""],
)

mask = details["StockCode"].str.strip().str.upper().eq("C2").fillna(False)
rows = details.loc[mask]

print(f"C2 共 {len(rows)} 条明细")
print(rows.to_string(index=False))

# %% [markdown]
# 原 Notebook 单元格 12
# 这里选取发现字母加数字是代表商品编号，无特殊意义，所以去除这一部分

# %% [markdown]
# 原 Notebook 单元格 13
# 这里发现此处修改指令后ai仍然没有修改正确，没有去除gift_0001_40这类下划线链接的字段（此处不列出错误内容，只作为流程记录）
#
# 以下是修正正确的版本

# %%
# 原 Notebook 单元格 14
from pathlib import Path

import pandas as pd

# 支持从项目根目录或 q1_data_quality 目录运行。
csv_path = DATA_PATH

raw = pd.read_csv(
    csv_path,
    usecols=["StockCode", "Quantity", "Price"],
    dtype="string",
    keep_default_na=False,
    na_values=[""],
)

stock_code = raw["StockCode"].str.strip()

# 整个编码必须由字母段组成，段与段之间允许空格或下划线。
pattern = r"[A-Za-z]+(?:[ _]+[A-Za-z]+)*"
matched = stock_code.str.fullmatch(pattern, na=False)

quantity = pd.to_numeric(raw["Quantity"], errors="raise")
price = pd.to_numeric(raw["Price"], errors="raise")
if quantity.isna().any() or price.isna().any():
    raise ValueError("数量或单价存在缺失，请先核查再计算金额占比。")

line_amount = quantity * price
matched_rows = int(matched.sum())
matched_amount = line_amount.loc[matched].sum()
total_amount = line_amount.sum()

by_code = (
    pd.DataFrame({
        "StockCode": stock_code.loc[matched],
        "明细金额": line_amount.loc[matched],
    })
    .groupby("StockCode", as_index=False)
    .agg(明细行数=("明细金额", "size"), 明细金额=("明细金额", "sum"))
    .sort_values(["明细行数", "StockCode"], ascending=[False, True])
)

print(f"命中编码数：{len(by_code):,}")
print(f"命中明细行数：{matched_rows:,}")
print(f"命中明细金额：{matched_amount:,.4f}")

if len(raw):
    print(f"占全表行数：{matched_rows / len(raw):.4%}")
if total_amount != 0:
    print(f"占全表带符号金额：{matched_amount / total_amount:.4%}")
else:
    print("全表带符号金额为 0，无法计算金额占比。")

print(by_code.round({"明细金额": 4}).to_string(index=False))

# %% [markdown]
# 原 Notebook 单元格 15
# 具体代表什么需要查看描述等

# %%
# 原 Notebook 单元格 16
details = pd.read_csv(
    csv_path,
    usecols=["StockCode", "Description", "Quantity", "Price"],
    dtype="string",
    keep_default_na=False,
    na_values=[""],
)

details["StockCode"] = details["StockCode"].str.strip()
selected = details.loc[details["StockCode"].isin(by_code["StockCode"])].copy()

selected["明细金额"] = (
    pd.to_numeric(selected["Quantity"], errors="raise")
    * pd.to_numeric(selected["Price"], errors="raise")
)

description_report = (
    selected.groupby(["StockCode", "Description"], dropna=False, as_index=False)
    .agg(明细行数=("明细金额", "size"), 明细金额=("明细金额", "sum"))
    .sort_values(["StockCode", "明细行数", "Description"], ascending=[True, False, True])
)

print(description_report.round({"明细金额": 4}).to_string(index=False))

# %% [markdown]
# 原 Notebook 单元格 17
# 只列举了部分，不能完全判断具体是什么，但是可以看出M和m是一个东西
#
# 下面比上一版多列了描述覆盖率、正负数量、零单价、取消行数和发票样例

# %%
# 原 Notebook 单元格 18
details = pd.read_csv(
    csv_path,
    usecols=["Invoice", "StockCode", "Description", "Quantity", "Price"],
    dtype="string",
    keep_default_na=False,
    na_values=[""],
)

details["StockCode"] = details["StockCode"].str.strip()
selected = details.loc[details["StockCode"].isin(by_code["StockCode"])].copy()

quantity = pd.to_numeric(selected["Quantity"], errors="raise")
price = pd.to_numeric(selected["Price"], errors="raise")

selected["明细金额"] = quantity * price
selected["正数量"] = quantity.gt(0)
selected["负数量"] = quantity.lt(0)
selected["零单价"] = price.eq(0)
selected["取消行"] = (
    selected["Invoice"].str.strip().str.upper().str.startswith("C", na=False)
)

evidence = (
    selected.groupby(["StockCode", "Description"], dropna=False, as_index=False)
    .agg(
        明细行数=("Invoice", "size"),
        正数量行数=("正数量", "sum"),
        负数量行数=("负数量", "sum"),
        零单价行数=("零单价", "sum"),
        取消行数=("取消行", "sum"),
        明细金额=("明细金额", "sum"),
        发票样例=("Invoice", "first"),
    )
)

code_rows = evidence.groupby("StockCode")["明细行数"].transform("sum")
evidence["描述占该编码行数(%)"] = (100 * evidence["明细行数"] / code_rows).round(2)

evidence = evidence[
    ["StockCode", "Description", "明细行数", "描述占该编码行数(%)",
     "正数量行数", "负数量行数", "零单价行数", "取消行数", "明细金额", "发票样例"]
].sort_values(["StockCode", "明细行数", "Description"], ascending=[True, False, True])

print(evidence.round({"明细金额": 4}).to_string(index=False))

# %% [markdown]
# 原 Notebook 单元格 19
# 由此不难看出哪怕是纯字母中，还有商品代码，例如PADS、DCGSSGIRL、DCGSSBOY等，还有一些数量极少且没有描述的项，能够判断特殊含义的项如下

# %% [markdown]
# 原 Notebook 单元格 20
# | StockCode | 可判断的业务含义| 
# |---|---|
# | POST | 邮费 | 
# | DOT | 邮费，原文标为网站邮费 |
# | BANK CHARGES | 银行费用 | 
# | AMAZONFEE | Amazon 相关费用 |
# | CRUK | 原文标为 CRUK 佣金 | 
# | D | 折扣 |
# | ADJUST | 调整记录 | 
# | B | 坏账调整 | 
# | M、m | 手工记录 |
# | S | 样品相关记录 | 

# %% [markdown]
# 原 Notebook 单元格 21
# 这些记录占总行数和总金额的比例分别是多少？

# %%
# 原 Notebook 单元格 22

# 按已核实的业务标签筛选，保留编码大小写。
special_codes = [
    "POST", "DOT", "BANK CHARGES", "AMAZONFEE", "CRUK",
    "D", "ADJUST", "B", "M", "m", "S",
]
stock_code = raw["StockCode"].str.strip()
is_special = stock_code.isin(special_codes)

quantity = pd.to_numeric(raw["Quantity"], errors="raise")
price = pd.to_numeric(raw["Price"], errors="raise")
if quantity.isna().any() or price.isna().any():
    raise ValueError("数量或单价存在缺失，请先核查再计算金额占比。")

# 逐行计算，保留正负号，包含取消和调整记录。
line_amount = quantity * price

total_rows = len(raw)
special_rows = int(is_special.sum())
total_amount = line_amount.sum()
special_amount = line_amount.loc[is_special].sum()

print(f"特殊业务编码命中明细：{special_rows:,} / {total_rows:,} 行")
if total_rows:
    print(f"占全表行数：{special_rows / total_rows:.4%}")

print(f"特殊业务编码带符号金额：{special_amount:,.4f}")
print(f"全表带符号金额：{total_amount:,.4f}")
if total_amount != 0:
    print(f"占全表带符号金额：{special_amount / total_amount:.4%}")
else:
    print("全表带符号金额为 0，无法计算金额占比。")

# %% [markdown]
# 原 Notebook 单元格 23
# **问题三**

# %% [markdown]
# 原 Notebook 单元格 24
# 同样是一个已经在q1.1发现并解决的问题，以下仅作整理

# %%
# 原 Notebook 单元格 25
from pathlib import Path

import pandas as pd


# 1. 读取数据，保留原始字段和值用于回查
csv_path = DATA_PATH

raw = pd.read_csv(
    csv_path,
    dtype="string",
    keep_default_na=False,
    na_values=[""],
)

df = raw.assign(
    Quantity=pd.to_numeric(raw["Quantity"], errors="raise"),
    Price=pd.to_numeric(raw["Price"], errors="raise"),
    InvoiceDate=pd.to_datetime(raw["InvoiceDate"], format="ISO8601", errors="raise"),
)


# 2. 打印数量极值对应的所有原始行，保留并列极值
min_quantity = df["Quantity"].min()
max_quantity = df["Quantity"].max()
min_mask = df["Quantity"].eq(min_quantity).fillna(False)
max_mask = df["Quantity"].eq(max_quantity).fillna(False)

print(f"最大数量 {max_quantity:,}，命中 {int(max_mask.sum()):,} 行")
print(raw.loc[max_mask].to_string(index=False))

print(f"\n最小数量 {min_quantity:,}，命中 {int(min_mask.sum()):,} 行")
print(raw.loc[min_mask].to_string(index=False))


# 3. 针对每条负数极值，在全表查找可能的原销售
# 候选条件：同客户、同商品、数量相反、正向记录时间更早，且发票号不是 C 开头。
# 单价相同作为额外证据单独展示，便于看到数量匹配但价格不同的候选。
invoice = df["Invoice"].str.strip().str.upper()
is_cancellation = invoice.str.startswith("C", na=False)

if min_quantity < 0:
    for row_index, returned in df.loc[min_mask].iterrows():
        return_invoice = returned["Invoice"]
        print(f"\n负数极值发票 {return_invoice}")

        if not is_cancellation.loc[row_index]:
            print("发票号未标记为 C 开头，不按取消记录匹配。")
            continue

        match_fields = ["Customer ID", "StockCode", "InvoiceDate"]
        if returned[match_fields].isna().any():
            print("缺少客户、商品或时间字段，无法按当前规则匹配。")
            continue

        candidate_mask = (
            df["Customer ID"].eq(returned["Customer ID"])
            & df["StockCode"].eq(returned["StockCode"])
            & df["Quantity"].eq(-returned["Quantity"])
            & df["InvoiceDate"].lt(returned["InvoiceDate"])
            & ~is_cancellation
        ).fillna(False)

        candidates = df.loc[
            candidate_mask,
            ["Invoice", "Customer ID", "StockCode", "Quantity", "Price", "InvoiceDate"],
        ].copy()

        candidates["与负数极值单价相同"] = candidates["Price"].eq(returned["Price"])
        candidates["距离取消的时间"] = returned["InvoiceDate"] - candidates["InvoiceDate"]
        candidates = candidates.sort_values("距离取消的时间")

        print(f"全表候选销售明细数 {len(candidates):,}")
        if not candidates.empty:
            print(candidates.to_string(index=False))


# 4. 查找全部负单价明细，并汇总共同特征
negative_price_mask = df["Price"].lt(0).fillna(False)
negative_price = df.loc[negative_price_mask].copy()

print(f"\n负单价明细共 {len(negative_price):,} 行")
print(raw.loc[negative_price_mask].to_string(index=False))

if not negative_price.empty:
    negative_price["发票字母前缀"] = invoice.loc[negative_price_mask].str.extract(
        r"^([A-Z]+)", expand=False
    )
    negative_price["客户ID缺失"] = negative_price["Customer ID"].isna()
    negative_price["明细金额"] = negative_price["Quantity"] * negative_price["Price"]

    profile = (
        negative_price.groupby(
            ["发票字母前缀", "StockCode", "Description", "Quantity", "客户ID缺失"],
            dropna=False,
            as_index=False,
        )
        .agg(明细行数=("Price", "size"), 带符号金额=("明细金额", "sum"))
    )

    print("\n负单价共同特征")
    print(profile.round({"带符号金额": 2}).to_string(index=False))

# %% [markdown]
# 原 Notebook 单元格 26
# 结论：
#
# 1.两条 Quantity 极值记录为真实记录，两条记录相隔 12 分钟，负数量记录的发票号以C开头，数量及明细金额正好抵消。这些证据支持将它们视为一组销售和取消的候选配对。当前核对范围是两端极值，原始列中没有提供直接的原单引用，尚未验证全表是否存在其他可匹配原单。清洗时应保留两条原始记录，再按销售和退货各自的口径处理。仅按数量阈值删除会丢失这组关联线索。
#
# 2.负单价：此前确认全表有 5 条，发票均以 A 开头，StockCode 均为 B，描述均为 Adjust bad debt，数量均为 1，客户 ID 均缺失。原始描述支持将这 5 条负单价明细归为坏账调整。原始层可保留，商品销售汇总时单独标识并排除。

# %% [markdown]
# 原 Notebook 单元格 27
# 如果你是数据工程师，会保留还是删除这些记录？说明你的判断标准

# %% [markdown]
# 原 Notebook 单元格 28
# | 记录 | 处理决定 | 判断依据 |
# |---|---|---|
# | 581483 和 C581484，数量分别为 80,995 和 −80,995 | 两条都保留，分别标记为正向销售记录和取消记录。在下单总额中可以计入正向明细，在净销售分析中应同时考虑取消冲减。 | 两行的客户、商品和单价相同，数量相反，取消记录晚 12 分钟。这些证据支持销售与取消的候选配对，但没有显式原单引用，也无法证明最初录入的数量准确。若仅因数量极端而删除其中一条，会破坏数量和金额的抵消关系。 |
# | 五条 Price < 0 的明细 | 原始记录保留，标记为坏账调整。从商品销售额中排除，在账务调整分析中单列。 | 五条均使用编码 B，描述均为 Adjust bad debt，发票号均以 A 开头。归类的主要依据是这些字段的一致性。 |

# %% [markdown]
# 原 Notebook 单元格 29
# **问题四**

# %%
# 原 Notebook 单元格 30
missing_customer = raw["Customer ID"].isna()

quantity = pd.to_numeric(raw["Quantity"], errors="raise")
price = pd.to_numeric(raw["Price"], errors="raise")
if quantity.isna().any() or price.isna().any():
    raise ValueError("数量或单价存在缺失，请先核查再计算金额占比。")

line_amount = quantity * price

total_rows = len(raw)
missing_rows = int(missing_customer.sum())
total_amount = line_amount.sum()
missing_amount = line_amount.loc[missing_customer].sum()

print(f"全表明细行数：{total_rows:,}")
print(f"缺失客户 ID 的明细行数：{missing_rows:,}")
print(f"全表带符号金额：{total_amount:,.2f}")
print(f"缺失组带符号金额：{missing_amount:,.2f}")

if total_rows:
    row_share = 100 * missing_rows / total_rows
    print(f"缺失组占全表明细行数：{row_share:.4f}%")

    if total_amount != 0:
        amount_share = 100 * missing_amount / total_amount
        print(f"缺失组占全表带符号金额：{amount_share:.4f}%")
        print(f"金额占比减行数占比：{amount_share - row_share:+.4f} 个百分点")
    else:
        print("全表带符号金额为 0，无法计算金额占比。")

# %% [markdown]
# 原 Notebook 单元格 31
# 缺失客户 ID 的记录占总行数的比例为22.7669%，这部分缺失记录占总金额的比例为13.6824%，相比来说，减少了-9.0845 个百分点，探究为什么会出现这个情况？思路：先看看少了的是哪部分?

# %% [markdown]
# 原 Notebook 单元格 32
# 补充：Q1.1 已经有一个对照结果：排除 C 开头发票，并限制数量和单价均为正之后，缺失组仍贡献了 22.6675% 的行数、15.3971% 的金额。这说明即使在这个正向口径下，缺失组的每行金额仍然较低。

# %%
# 原 Notebook 单元格 33
import pandas as pd

data = pd.read_csv(
    csv_path,
    usecols=["Invoice", "Customer ID", "Quantity", "Price"],
    dtype="string",
    keep_default_na=False,
    na_values=[""],
)

quantity = pd.to_numeric(data["Quantity"], errors="raise")
price = pd.to_numeric(data["Price"], errors="raise")
if quantity.isna().any() or price.isna().any():
    raise ValueError("数量或单价存在缺失，请先核查。")

amount = quantity * price
is_cancel = data["Invoice"].str.strip().str.upper().str.startswith("C", na=False)

# 优先识别取消发票，再检查非取消明细的单价和金额。
category = pd.Series("其他负金额明细", index=data.index, dtype="string")
category.loc[amount.gt(0)] = "正金额明细"
category.loc[amount.eq(0)] = "零金额明细"
category.loc[price.lt(0)] = "负单价明细"
category.loc[is_cancel] = "C 开头的取消明细"

customer_group = (
    data["Customer ID"].isna()
    .map({True: "ID 缺失", False: "ID 非缺失"})
)

detail = pd.DataFrame({
    "客户组": customer_group,
    "明细类型": category,
    "明细金额": amount,
})

group_sizes = detail.groupby("客户组").size()

breakdown = (
    detail.groupby(["客户组", "明细类型"], as_index=False)
    .agg(明细行数=("明细金额", "size"), 金额合计=("明细金额", "sum"))
)

denominator = breakdown["客户组"].map(group_sizes)
breakdown["占组内行数(%)"] = 100 * breakdown["明细行数"] / denominator
breakdown["该类型平均每行金额"] = breakdown["金额合计"] / breakdown["明细行数"]
breakdown["每百行金额贡献"] = 100 * breakdown["金额合计"] / denominator

display(breakdown.round(4))

comparison = breakdown.pivot(
    index="明细类型", columns="客户组", values="每百行金额贡献"
).fillna(0)

comparison["缺失组减非缺失组"] = comparison["ID 缺失"] - comparison["ID 非缺失"]
display(comparison.sort_values("缺失组减非缺失组").round(2))

# %% [markdown]
# 原 Notebook 单元格 34
# 因为存在负金额所有总金额占比抵消了一部分（我的理解）

# %% [markdown]
# 原 Notebook 单元格 35
# 缺失 CustomerID 的记录与有 CustomerID 的记录在以下维度上有什么差异？
# 国家分布
# 客单价
# 高频商品
#
# 思路：差异主要可以从什么角度看？占比比较，数量比较，特征值？

# %% [markdown]
# 原 Notebook 单元格 36
# 以下为ai给出的比较建议
# | 维度 | 建议比较 | 为什么这样看 |
# |---|---|---|
# | **国家分布** | 各国明细行数、各国占本组的比例、两组占比差、各国自身的 ID 缺失率 | 「缺失组有多少来自英国」和「英国明细中有多少缺 ID」的分母不同。前者看组内构成，后者定位缺失集中的国家。 |
# | **客单价** | 发票数、平均每张发票金额、中位数、P90 | 均值容易受高金额发票影响。均值和中位数一起看，可以判断差异是否也出现在典型发票上。缺 ID 时无法按人计算，这里把客单价明确定义为**每张发票的平均金额**。 |
# | **高频商品** | 含该商品的发票数、占本组发票的比例、两组排名、TOP 10 重合数 | 同一商品在同一张发票里出现多行时只算一次。用「每 100 张发票有多少张包含它」比较两组，可以避免大组单靠规模占优。 |

# %% [markdown]
# 原 Notebook 单元格 37
# 读取数据并标记缺失组

# %%
# 原 Notebook 单元格 38
from pathlib import Path

import pandas as pd

csv_path = DATA_PATH

data = pd.read_csv(
    csv_path,
    usecols=["Invoice", "StockCode", "Country", "Customer ID", "Quantity", "Price"],
    dtype="string",
    keep_default_na=False,
    na_values=[""],
)

data["Quantity"] = pd.to_numeric(data["Quantity"], errors="raise")
data["Price"] = pd.to_numeric(data["Price"], errors="raise")
if data[["Quantity", "Price"]].isna().any().any():
    raise ValueError("数量或单价有缺失，请先核查。")

data["Invoice"] = data["Invoice"].str.strip()
data["StockCode"] = data["StockCode"].str.strip()
data["ID缺失"] = data["Customer ID"].isna()
data["客户组"] = data["ID缺失"].map({True: "ID 缺失", False: "ID 非缺失"})
data["明细金额"] = data["Quantity"] * data["Price"]

# %% [markdown]
# 原 Notebook 单元格 39
# 国家分布：同时看组内构成和各国缺失率
# 这里使用全量明细，回答客户 ID 缺失记录在原始数据中如何分布。（2编：对应客户分区）

# %%
# 原 Notebook 单元格 40
country_counts = pd.crosstab(
    data["Country"].fillna("国家缺失"),
    data["客户组"],
)

country_report = pd.DataFrame({
    "缺失组行数": country_counts["ID 缺失"],
    "非缺失组行数": country_counts["ID 非缺失"],
    "缺失组内占比(%)": 100 * country_counts["ID 缺失"] / country_counts["ID 缺失"].sum(),
    "非缺失组内占比(%)": (
        100 * country_counts["ID 非缺失"] / country_counts["ID 非缺失"].sum()
    ),
    "该国ID缺失率(%)": 100 * country_counts["ID 缺失"] / country_counts.sum(axis=1),
})

country_report["组内占比差(百分点)"] = (
    country_report["缺失组内占比(%)"] - country_report["非缺失组内占比(%)"]
)

country_report = country_report.sort_values(
    "组内占比差(百分点)", key=lambda values: values.abs(), ascending=False
)
display(country_report.round(4))

# %% [markdown]
# 原 Notebook 单元格 41
# 对于大部分国家来说都是非缺失组内占比比缺失组内占比多，对于英国来说绝对不能删除ID缺失项，不然会对结果有很大的影响

# %% [markdown]
# 原 Notebook 单元格 42
# 3. 客单价（2编：对应销售总额统计 / 报表）

# %% [markdown]
# 原 Notebook 单元格 43
# 这个地方最开始想的太简单了，没有考虑到重复计算的情况，同时忽略了前面发现的非商品编码的金额对于该项的理解，此处应该删除c开头的以及特殊商品

# %%
# 原 Notebook 单元格 44
special_codes = {
    "POST", "DOT", "BANK CHARGES", "AMAZONFEE", "CRUK",
    "D", "ADJUST", "B", "M", "m", "S",
}

valid_invoice = data["Invoice"].fillna("").ne("")
valid_code = data["StockCode"].fillna("").ne("")
is_cancel = data["Invoice"].str.upper().str.startswith("C", na=False)

sales = data.loc[
    valid_invoice
    & valid_code
    & ~is_cancel
    & data["Quantity"].gt(0)
    & data["Price"].gt(0)
    & ~data["StockCode"].isin(special_codes)
].copy()

orders = sales.groupby("Invoice").agg(
    发票金额=("明细金额", "sum"),
    明细行数=("ID缺失", "size"),
    ID缺失行数=("ID缺失", "sum"),
)

mixed_id = orders["ID缺失行数"].gt(0) & orders["ID缺失行数"].lt(orders["明细行数"])
print("纳入明细中同时有缺 ID 和有 ID 的发票数", int(mixed_id.sum()))

comparable_orders = orders.loc[~mixed_id].copy()
comparable_orders["客户组"] = comparable_orders["ID缺失行数"].gt(0).map({
    True: "ID 缺失",
    False: "ID 非缺失",
})

order_report = comparable_orders.groupby("客户组").agg(
    发票数=("发票金额", "size"),
    总金额=("发票金额", "sum"),
    平均每张发票金额=("发票金额", "mean"),
    中位数=("发票金额", "median"),
    P90=("发票金额", lambda values: values.quantile(0.90)),
    平均每张发票明细行数=("明细行数", "mean"),
)
display(order_report.round(2))

# %% [markdown]
# 原 Notebook 单元格 45
# 虽然id缺失的发票数不多，当是金额大，用平均数和中位数比较发现是受部分极大值影响

# %% [markdown]
# 原 Notebook 单元格 46
# 4.高频商品（2编:对应商品推荐模型，需要对比来判断能不能删除这些ID缺失项）

# %%
# 原 Notebook 单元格 47
invoice_products = (
    sales[["Invoice", "StockCode"]]
    .drop_duplicates()
    .join(comparable_orders[["客户组"]], on="Invoice", how="inner")
)

product_report = (
    invoice_products.groupby(["客户组", "StockCode"], as_index=False)
    .agg(覆盖发票数=("Invoice", "size"))
    .sort_values(["客户组", "覆盖发票数", "StockCode"],
                 ascending=[True, False, True])
)

order_counts = comparable_orders.groupby("客户组").size()
product_report["组内发票覆盖率(%)"] = (
    100 * product_report["覆盖发票数"] / product_report["客户组"].map(order_counts)
)
product_report["组内排名"] = product_report.groupby("客户组").cumcount() + 1

top_10 = product_report.loc[product_report["组内排名"].le(10)]
display(top_10.round(4))

# 对两组 TOP 10 的并集，补出这些编码在另一组中的覆盖率。
top_codes = top_10["StockCode"].unique()
coverage = (
    product_report.loc[product_report["StockCode"].isin(top_codes)]
    .pivot(index="StockCode", columns="客户组", values="组内发票覆盖率(%)")
    .reindex(columns=["ID 缺失", "ID 非缺失"])
    .fillna(0)
)
coverage["缺失组减非缺失组(百分点)"] = coverage["ID 缺失"] - coverage["ID 非缺失"]
display(coverage.round(4))

missing_top = set(top_10.loc[top_10["客户组"].eq("ID 缺失"), "StockCode"])
known_top = set(top_10.loc[top_10["客户组"].eq("ID 非缺失"), "StockCode"])
print("两组 TOP 10 重合的编码数", len(missing_top & known_top))

# %% [markdown]
# 原 Notebook 单元格 48
# 思考：观察这些差异有什么用？

# %% [markdown]
# 原 Notebook 单元格 49
# | 比较什么 | 对清洗决策有什么用 |
# |---|---|
# | **国家分布** | 判断删行对哪些地区影响更大。你已经算出英国明细的 ID 缺失率是 **24.46%**，非英国合计约 **3.46%**。统一删除缺 ID 明细会让英国在剩余数据中的占比下降，影响地区销售对比。 |
# | **客单价** | 判断只看有 ID 的发票，会把整体的**平均每张发票金额**推高还是拉低。之前确认缺 ID 组的**每条正金额明细**金额较低，但一张发票可能有很多条明细，所以仍需按发票汇总后再判断。 |
# | **高频商品** | 判断只用有 ID 的发票做商品分析，会低估哪些商品的出现频率。比如 85099B 在缺 ID 组的发票覆盖率是 **24.94%**，在有 ID 组是 **8.90%**。按发票做购物篮分析时，保留符合交易口径的缺 ID 发票，仍能利用这些商品共现记录。 |

# %% [markdown]
# 原 Notebook 单元格 50
# so到这一步为止，都是为了给不同下游途径提供数据清洗的方案

# %% [markdown]
# 原 Notebook 单元格 51
# 你能推测这些"匿名"记录是什么人群吗

# %% [markdown]
# 原 Notebook 单元格 52
# 英国人占比多，初步估计是英国人，但是这并不是一个准确的分类，难道是英国人普遍不实名上网吗？（不确定）
