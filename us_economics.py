import streamlit as st
import pandas as pd
import numpy as np
from fredapi import Fred
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
from datetime import datetime, timedelta

# ==========================================
# 1. 配置与初始化
# ==========================================
st.set_page_config(page_title="US 美国经济数据监测", layout="wide")
st.title("🇺🇸 美国经济数据监测系统")

# API Key 配置
API_KEY = st.secrets["FRED_API_KEY"]

# 侧边栏：配置优化
with st.sidebar:
    st.header("系统设置")
    with st.expander("⚙️ 高级参数设置 (Advanced)", expanded=False):
        lookback_years = st.slider("数据获取长度 (Years)", 5, 30, 15, help="从 FRED 拉取多少年的历史数据，建议设大一点以备分析")
        z_score_window = st.slider("宏观周期图-滚动窗口 (Months)", 12, 120, 60, help="仅影响【宏观周期定位】图的平滑程度")
    
    st.info("""
    **核心数据发布日历**：
    - **非农/失业率**：每月第一个周五
    - **初请失业金**：每周四发布上月数据
    - **CPI / 零售销售**：每月中旬发布上月数据
    - **PCE (核心通胀)**：每月月末
    - **GDP (初值)**：1, 4, 7, 10月 下旬
    - **美联储议息**：约每 6 周一次
    """)

# ==========================================
# 2. 核心指标定义
# ==========================================
INDICATORS = {
    "就业 (Employment)": {
        "非农就业人数 (Non-Farm Payrolls)": "PAYEMS",
        "失业率 (Unemployment Rate)": "UNRATE", 
        "初请失业金 (Initial Claims)": "ICSA"
    },
    "消费 (Consumption)": {
        "零售销售 (Retail Sales)": "RSAFS",
        "个人消费支出 (PCE)": "PCE",
        "消费者信心 (UMich Sentiment)": "UMCSENT"
    },
    "增长 (Growth)": {
        "实际GDP (Real GDP)": "GDPC1",
        "工业产出 (Industrial Production)": "INDPRO",
        "耐用品订单 (Durable Goods)": "DGORDER"
    },
    "通胀 (Inflation)": {
        "CPI (All Urban)": "CPIAUCSL",
        "核心 PCE (Core PCE)": "PCEPILFE",
        "PPI (Producer Price Index)": "PPIFIS"
    }
}

INVERSE_CODES = ["UNRATE", "ICSA"]

NAME_TO_CODE = {}
for cat, items in INDICATORS.items():
    for name, code in items.items():
        NAME_TO_CODE[name] = code

# === 升级：全指标深度解读百科 ===
INDICATOR_EXPLANATIONS = {
    "就业 (Employment)": """
    #### 📘 就业指标详解
    
    **1. 非农就业人数 (Non-Farm Payrolls)**
    * **图表数值含义**：**月度新增人数 (MoM Change)，即本月比上月增加了多少人（单位：千人）。**
    * **定义**：除了农业部门以外，美国所有企业创造的新增就业岗位数量。
    * **重要性**：⭐⭐⭐⭐⭐ 它是美联储制定货币政策的核心依据，也是市场波动最大的来源。
    * **怎么看**：
        * **强劲 (>20万人)**：经济火热，美联储可能维持高利率。
        * **温和 (10-20万人)**：经济“软着陆”的理想区间。
        * **疲软 (<10万人)**：经济衰退风险上升。
    
    **2. 失业率 (Unemployment Rate)**
    * **图表数值含义**：**百分比 (%)，当前失业人口占劳动力总人口的比例（绝对值）。**
    * **定义**：劳动力中正在积极寻找工作但找不到工作的人口比例
    * **重要性**：⭐⭐⭐⭐。滞后指标，通常在经济衰退开始后才会大幅上升。
    * **阈值**：4.0% 是心理关口。若突破并持续上升（触发“萨姆规则”），通常意味着衰退已至。
    
    **3. 初请失业金人数 (Initial Claims)**
    * **图表数值含义**：**当周申请人数，上周首次去申请失业救济的绝对人数**。
    * **定义**：上周首次去政府申请失业救济金的人数。
    * **重要性**：⭐⭐⭐⭐。最高频的指标（周更），是就业市场的先行指标。
    * **阈值**：20万以下为极好；30万以上为危险信号。
    """,
    
    "消费 (Consumption)": """
    #### 📘 消费指标详解
    
    **1. 零售销售 (Retail Sales) 同比增速 (YoY %)**
    * **定义**：零售商店与食品服务的销售总额 (RSAFS) 销售额总计。因为波动大且影响力大。
    * **重要性**：⭐⭐⭐⭐⭐。美国经济约70%由消费驱动，这是衡量内需（含商品与餐饮）最硬核的指标。
    * **怎么看**：若同比增速跑输通胀（例如低于3%），说明实际消费在萎缩。
    
    **2. 个人消费支出 (PCE) 同比增速 (YoY %)**
    * **定义**：家庭在商品和服务上的支出。比零售销售覆盖面更广（包含医疗等服务消费）。
    * **重要性**：⭐⭐⭐⭐。是GDP计算的直接输入变量。
    
    **3. 密歇根大学消费者信心指数 (Sentiment) (Index Value)**
    * **定义**：通过电话调查问卷得出的消费者乐观程度。数值越高，消费者越乐观。
    * **重要性**：⭐⭐⭐。属于“软数据”或先行指标。信心崩塌往往发生在支出减少之前。
    """,
    
    "增长 (Growth)": """
    #### 📘 经济增长指标详解
    
    **1. 实际 GDP (Real GDP) 同比增速 (YoY %)**
    * **定义**：剔除通胀影响后的国内生产总值。
    * **重要性**：⭐⭐⭐⭐⭐。经济的最终成绩单。
    * **注意**：这是**季度数据**。通常连续两个季度负增长被定义为“技术性衰退”。
    
    **2. 工业产出 (Industrial Production) 同比增速 (YoY %)**
    * **定义**：工厂、矿山和公用事业的实际产出量。
    * **重要性**：⭐⭐⭐⭐。虽然美国是服务业大国，但制造业对周期最敏感。产出下降往往是衰退的先导。
    
    **3. 耐用品订单 (Durable Goods) 同比增速 (YoY %)**
    * **定义**：寿命超过3年的商品（如飞机、机械、汽车）的订单。
    * **重要性**：⭐⭐⭐。代表企业的长期投资信心。如果企业不敢买设备，说明看空未来。
    """,
    
    "通胀 (Inflation)": """
    #### 📘 通胀指标详解
    
    **1. CPI (消费者物价指数) 同比增速 (YoY %)**
    * **定义**：一篮子商品和服务的价格变化。民众感知最强。
    * **重要性**：⭐⭐⭐⭐⭐。决定了你的钱是否贬值，以及工资是否需要上涨（工资-通胀螺旋）。
    
    **2. 核心 PCE (Core PCE) 同比增速 (YoY %)**
    * **定义**：剔除波动较大的食品和能源后的个人消费支出价格指数。
    * **重要性**：⭐⭐⭐⭐⭐。**美联储最爱**。联储说的“2%通胀目标”指的就是这个指标，而不是CPI。
    
    **3. PPI (生产者价格指数) 同比增速 (YoY %)**
    * **定义**：工厂出厂价格。
    * **重要性**：⭐⭐⭐。CPI的先行指标。如果工厂成本涨了，最终会传导给消费者。
    """
}
# ==========================================
# 3. 数据获取与处理
# ==========================================
@st.cache_data(ttl=3600)
def fetch_and_process_data(api_key, indicators, years):
    if not api_key:
        return None
    fred = Fred(api_key=api_key)
    start_date = datetime.now() - timedelta(days=years*365)
    all_data = pd.DataFrame()
    flat_indicators = {}
    for category, items in indicators.items():
        for name, code in items.items():
            flat_indicators[name] = code
    progress_bar = st.progress(0)
    for i, (name, code) in enumerate(flat_indicators.items()):
        try:
            series = fred.get_series(code, observation_start=start_date)
            series.name = name
            series = series.resample('M').last()
            all_data = pd.concat([all_data, series], axis=1)
        except Exception as e:
            st.warning(f"无法获取 {name} ({code}): {e}")
        progress_bar.progress((i + 1) / len(flat_indicators))
    progress_bar.empty()
    if not all_data.empty:
        all_data.sort_index(inplace=True)
        all_data.index = pd.to_datetime(all_data.index)
    return all_data

def calculate_quant_metrics(df, z_window):
    metrics_df = pd.DataFrame(index=df.index)
    for col in df.columns:
        code = NAME_TO_CODE.get(col)
        # 1. 市场视角 (Market View)
        if code == "PAYEMS": 
            metrics_df[f"{col}_Market"] = df[col].diff(1) 
        elif code in ["UNRATE", "ICSA", "UMCSENT"]: 
            metrics_df[f"{col}_Market"] = df[col]
        else:
            metrics_df[f"{col}_Market"] = df[col].pct_change(12) * 100
        # 2. 动量视角 (Momentum for Heatmap) & 原始值 (for Radar)
        series_filled = df[col].ffill()
        if code in ["UNRATE", "ICSA", "UMCSENT"]:
            # 对于雷达图，我们需要一个“越大越好”的排名
            # 虽然这里计算的是yoy，但我们也保存一个用于排名的 raw_val
            # 简单起见，我们直接保存填充后的原始值作为 _Raw，在雷达图逻辑中处理反向逻辑
            metrics_df[f"{col}_Raw"] = series_filled
            yoy = series_filled.diff(12)
        else:
            metrics_df[f"{col}_Raw"] = series_filled.pct_change(12) * 100
            yoy = series_filled.pct_change(12) * 100
            
        if code in INVERSE_CODES:
             yoy = -yoy 
        metrics_df[f"{col}_Momentum"] = yoy
        
        # 3. Z-Score
        rolling_mean = yoy.rolling(window=z_window).mean()
        rolling_std = yoy.rolling(window=z_window).std()
        if rolling_std.iloc[-1] == 0:
            metrics_df[f"{col}_Z"] = 0
        else:
            metrics_df[f"{col}_Z"] = (yoy - rolling_mean) / rolling_std
    return metrics_df

# ==========================================
# 4. 智能研报生成
# ==========================================
def generate_smart_report(category, df):
    report_text = f"### 📝 {category} · 总结\n\n"
    
    # 获取该板块下指标的最新有效值
    latest_vals = {}
    indicators = INDICATORS[category]
    
    for name, code in indicators.items():
        col_name = f"{name}_Market"
        if col_name in df.columns:
            valid = df[col_name].dropna()
            if not valid.empty:
                # 获取最新值和前值
                latest_vals[code] = (valid.iloc[-1], valid.iloc[-2] if len(valid)>1 else 0)

    # 辅助函数：计算环比/同比变动方向
    def get_trend_str(now, prev):
        diff = now - prev
        return "回升" if diff > 0 else "回落"

    # --- 1. 就业板块分析逻辑 (Employment) ---
    if category == "就业 (Employment)":
        nfp_now, nfp_prev = latest_vals.get('PAYEMS', (0,0))
        unrate_now, unrate_prev = latest_vals.get('UNRATE', (0,0))
        claims_now, claims_prev = latest_vals.get('ICSA', (0,0))
        
        report_text += "#### 1. 劳动力市场核心数据追踪\n"
        report_text += f"- **非农就业 (NFP)**：本月新增 **{nfp_now:,.0f}k** (前值 {nfp_prev:,.0f}k)。"
        
        # 非农判定
        if nfp_now > 250:
            report_text += " 数据**显著超预期**，显示劳动力市场极度火热。企业招聘意愿未受高利率显著抑制，这可能推高薪资通胀螺旋风险，迫使美联储维持鹰派立场。\n"
        elif 150 <= nfp_now <= 250:
            report_text += " 数据处于**稳健区间**。就业增长既未过热也未失速，符合“软着陆”路径特征，能为消费提供支撑，同时不至于引发过度通胀担忧。\n"
        elif 50 <= nfp_now < 150:
            report_text += " 就业增长**温和放缓**，显示紧缩政策正在生效，劳动力供需缺口逐渐弥合。\n"
        else:
            report_text += " 数据**大幅不及预期**，敲响衰退警钟。需密切关注是否受罢工或天气等短期因素扰动，否则市场将迅速计入降息预期。\n"

        report_text += f"- **失业率**：录得 **{unrate_now:.1f}%** ({get_trend_str(unrate_now, unrate_prev)} {abs(unrate_now-unrate_prev):.1f} pct)。"
        if unrate_now >= 4.5:
            report_text += " 失业率已明显脱离历史低位，表明劳动力市场闲置产能增加，经济下行压力实质性加大。\n"
        elif unrate_now > 4.0:
            report_text += " 突破 **4.0%** 心理关口，虽然历史上看仍属低位，但上升趋势确立（符合萨姆规则预警特征），需警惕负反馈循环。\n"
        else:
            report_text += " 仍处于**充分就业**水平，显示经济韧性极强，这也是支撑美联储“更高更久（Higher for Longer）”利率政策的底气。\n"

        if claims_now > 0:
             report_text += f"- **高频监测**：初请失业金人数为 **{claims_now:,.0f}**，"
             if claims_now < 220000:
                 report_text += "处于历史低位，裁员浪潮尚未广泛出现。"
             elif claims_now > 300000:
                 report_text += "已升至警戒水位，暗示就业市场拐点已至。"
             else:
                 report_text += "处于正常波动区间。"

    # --- 2. 通胀板块分析逻辑 (Inflation) ---
    elif category == "通胀 (Inflation)":
        cpi_now, cpi_prev = latest_vals.get('CPIAUCSL', (0,0))
        pce_now, pce_prev = latest_vals.get('PCEPILFE', (0,0))
        ppi_now, _ = latest_vals.get('PPIFIS', (0,0))
        
        report_text += "#### 1. 物价压力全景评估\n"
        report_text += f"- **CPI (消费者物价)**：同比增速 **{cpi_now:.2f}%** (前值 {cpi_prev:.2f}%，{get_trend_str(cpi_now, cpi_prev)})。"
        
        if cpi_now > 3.5:
            report_text += " 通胀处于**高位运行**阶段。粘性依然顽固，远高于美联储目标，购买力缩水将持续压制实际消费增长。\n"
        elif 2.5 < cpi_now <= 3.5:
            report_text += " 处于**去通胀（Disinflation）**的“最后一公里”。虽然大方向向下，但回落速度放缓，可能会经历波折。\n"
        elif cpi_now <= 2.5:
            report_text += " 已基本回归至**合意区间**，通胀风险解除，市场焦点将从“抗通胀”转向“保增长”。\n"
            
        report_text += f"- **核心 PCE (美联储锚点)**：同比 **{pce_now:.2f}%**。"
        spread = pce_now - 2.0
        if spread > 1.0:
            report_text += f" 距离2%目标仍有 **{spread:.1f}%** 的差距，表明服务业通胀压力尚未出清。\n"
        else:
            report_text += " 核心指标表现良好，为货币政策转向提供了数据支持。\n"
            
        report_text += f"- **PPI (上游成本)**：同比 **{ppi_now:.2f}%**。"
        if ppi_now > cpi_now:
            report_text += " 生产端价格涨幅高于消费端，企业利润率可能面临压缩风险。"
        else:
            report_text += " 上游成本压力缓解，有利于未来CPI的进一步回落。"

    # --- 3. 消费板块分析逻辑 (Consumption) ---
    elif category == "消费 (Consumption)":
        retail_now, retail_prev = latest_vals.get('RSXFS', (0,0))
        sent_now, sent_prev = latest_vals.get('UMCSENT', (0,0))
        
        report_text += "#### 1. 需求端韧性透视\n"
        report_text += f"- **零售销售**：同比增速 **{retail_now:.2f}%** ({get_trend_str(retail_now, retail_prev)})。"
        
        if retail_now > 5.0:
            report_text += " 消费动能**异常强劲**。在超额储蓄消耗殆尽的背景下，这主要由强劲的劳动力市场支撑。经济呈现“不着陆（No Landing）”特征。\n"
        elif 2.0 <= retail_now <= 5.0:
            report_text += " 消费保持**温和扩张**。这是一种健康的增长模式，既维持了经济运转，又未造成过热。\n"
        elif 0 <= retail_now < 2.0:
            report_text += " 增长**显露疲态**。考虑到通胀因素，实际零售可能已经负增长，居民消费降级迹象明显。\n"
        else:
            report_text += " 出现**同比萎缩**，这是经济衰退最直接的信号之一，表明高利率对需求的抑制作用已完全显现。\n"
            
        report_text += f"- **消费者信心指数**：读数 **{sent_now:.1f}**。"
        if sent_now > 80:
            report_text += " 处于乐观区间，居民对未来收入和经济前景看好，倾向于增加支出。\n"
        elif sent_now < 60:
            report_text += " 处于悲观区间，极低的情绪往往预示着未来几个月可选消费支出的缩减。\n"

    # --- 4. 增长板块分析逻辑 (Growth) ---
    elif category == "增长 (Growth)":
        gdp_now, gdp_prev = latest_vals.get('GDPC1', (0,0))
        ind_now, ind_prev = latest_vals.get('INDPRO', (0,0))
        
        report_text += "#### 1. 宏观基本面扫描\n"
        report_text += f"- **实际 GDP**：同比增速 **{gdp_now:.2f}%**。"
        
        # 美国长期潜在增长率约为 1.8% - 2.0%
        if gdp_now > 2.5:
            report_text += " 经济增速显著**高于潜在增长率**，显示出美国经济的“例外主义”韧性。衰退叙事被证伪。\n"
        elif 1.0 <= gdp_now <= 2.5:
            report_text += " 经济沿着**长期趋势线**运行，处于典型的周期中段稳态。\n"
        elif 0 < gdp_now < 1.0:
            report_text += " 经济处于**失速边缘**（Stall Speed），任何外部冲击都可能将其推入衰退。\n"
        else:
            report_text += " 经济已陷入**技术性萎缩**，确认进入衰退周期。\n"
            
        report_text += f"- **工业产出**：同比 **{ind_now:.2f}%**。"
        if ind_now < 0:
            report_text += " 制造业持续处于**去库存/收缩**周期，受全球需求疲软和强势美元压制明显。"
        else:
            report_text += " 工业生产保持正增长，实体经济基本盘稳固。"

    report_text += "\n\n---\n*💡 **分析摘要**：本报告基于 FRED 最新发布的原始数据，结合通用宏观分析框架自动生成。*"
    return report_text

# ==========================================
# 5. 界面主逻辑
# ==========================================

if API_KEY:
    raw_df = fetch_and_process_data(API_KEY, INDICATORS, lookback_years)
    
    if raw_df is not None and not raw_df.empty:
        quant_df = calculate_quant_metrics(raw_df, z_score_window)
        
        st.subheader("四大经济数据概览")
        st.caption("展示各板块核心代表指标的最新数值。就业看新增(人)，其他看同比增速(YoY%)。")
        
        latest_metrics = {}
        for category, items in INDICATORS.items():
            first_metric = list(items.keys())[0]
            try:
                valid_series = quant_df[f"{first_metric}_Market"].dropna()
                if not valid_series.empty:
                    val = valid_series.iloc[-1]
                    date = valid_series.index[-1]
                    latest_metrics[category] = (val, date, first_metric)
            except KeyError:
                continue

        col1, col2, col3, col4 = st.columns(4)
        cols = [col1, col2, col3, col4]
        
        for idx, (cat, (val, date, metric_name)) in enumerate(latest_metrics.items()):
            if idx < 4:
                display_val = ""
                label_suffix = ""
                if "Non-Farm" in metric_name:
                    display_val = f"{val:,.0f} k"
                    label_suffix = " (新增人数)"
                elif "Rate" in metric_name or "Sentiment" in metric_name:
                     display_val = f"{val:.1f}"
                else:
                    display_val = f"{val:.2f}%"
                    label_suffix = " (YoY)"
                
                state_tag = "平稳"
                if "Non-Farm" in metric_name:
                    state_tag = " 强劲" if val > 200 else (" 降温" if val < 100 else "⚖ 温和")
                elif "CPI" in metric_name:
                    state_tag = " 高位" if val > 3 else "✅ 达标"
                
                with cols[idx].container(border=True):
                    st.metric(
                        label=f"{cat.split(' ')[0]} - {metric_name.split('(')[0].strip()}", 
                        value=display_val
                    )
                    st.caption(f"当前状态: {state_tag}")

        # --- 深度分析 Tabs ---
        tab1, tab2, tab3, tab4 = st.tabs([" 趋势分析 & 研报", " 宏观周期定位", " 动态 Z-Score 热力图", "经济状态雷达"])

        
        # Tab 1: 趋势分析 & 智能研报
        with tab1:
            col_left, col_right = st.columns([2, 1])
            
            with col_left:
                selected_cat = st.selectbox("选择分析板块", list(INDICATORS.keys()))
                
                # 绘图逻辑
                if selected_cat == "就业 (Employment)":
                    nfp_col = "非农就业人数 (Non-Farm Payrolls)"
                    if f"{nfp_col}_Market" in quant_df.columns:
                        nfp_data = quant_df[f"{nfp_col}_Market"].dropna()
                        fig_nfp = go.Figure()
                        colors = ['#ef553b' if v < 0 else '#636efa' for v in nfp_data.values]
                        fig_nfp.add_trace(go.Bar(
                            x=nfp_data.index, y=nfp_data.values, marker_color=colors, name="新增就业"
                        ))
                        fig_nfp.update_layout(title="非农就业人数 (每月新增 / 千人)", hovermode="x unified", height=350)
                        st.plotly_chart(fig_nfp, use_container_width=True)
                    
                    fig_rate = make_subplots(specs=[[{"secondary_y": True}]])
                    ur_col = "失业率 (Unemployment Rate)"
                    ic_col = "初请失业金 (Initial Claims)"
                    if f"{ur_col}_Market" in quant_df.columns:
                        fig_rate.add_trace(go.Scatter(x=quant_df.index, y=quant_df[f"{ur_col}_Market"], name="失业率 (%)", line=dict(color='orange')), secondary_y=True)
                    if f"{ic_col}_Market" in quant_df.columns:
                        fig_rate.add_trace(go.Scatter(x=quant_df.index, y=quant_df[f"{ic_col}_Market"], name="初请失业金", line=dict(color='gray')), secondary_y=False)
                    fig_rate.update_layout(title="失业率 vs 初请失业金", hovermode="x unified", height=350)
                    st.plotly_chart(fig_rate, use_container_width=True)

                else:
                    fig = make_subplots(specs=[[{"secondary_y": True}]])
                    has_secondary = False
                    for name in INDICATORS[selected_cat].keys():
                        series = quant_df[f"{name}_Market"]
                        on_secondary = False
                        if "Rate" in name or "Sentiment" in name or "%" in name or "CPI" in name or "PCE" in name:
                             on_secondary = True
                             has_secondary = True
                        fig.add_trace(go.Scatter(x=series.index, y=series.values, name=name), secondary_y=on_secondary)
                    fig.update_layout(title=f"{selected_cat} - 核心趋势 同比增速 (YoY %)", hovermode="x unified", height=450)
                    st.plotly_chart(fig, use_container_width=True)

                
                st.markdown("---")
                smart_report = generate_smart_report(selected_cat, quant_df)
                st.info(smart_report)

        
            with col_right:
                st.markdown(INDICATOR_EXPLANATIONS.get(selected_cat, "暂无解读"))

        # Tab 2: 宏观周期
        with tab2:
            col_t1, col_t2 = st.columns([3, 1])
            with col_t1:
                st.markdown("##### 宏观经济周期：增长 vs 通胀")
            with col_t2:
                cycle_years = st.slider("⏱️ 观察窗口 (年)", 1, 10, 5, key="cycle_slider")
            
            try:
                growth_col = "工业产出 (Industrial Production)_Z"
                inflation_col = "核心 PCE (Core PCE)_Z"
                months_to_show = cycle_years * 12
                cycle_df = quant_df[[growth_col, inflation_col]].dropna().tail(months_to_show).copy()
                cycle_df['Date'] = cycle_df.index.strftime('%Y-%m')
                
                fig_cycle = px.scatter(
                    cycle_df, x=growth_col, y=inflation_col, text='Date', color=cycle_df.index,
                    title=f"经济路径 (过去 {cycle_years} 年)"
                )
                fig_cycle.add_hrect(y0=0, y1=6, fillcolor="red", opacity=0.05, annotation_text="滞胀/过热")
                fig_cycle.add_hrect(y0=-6, y1=0, fillcolor="green", opacity=0.05, annotation_text="复苏/通缩")
                fig_cycle.add_vline(x=0, line_dash="dash", line_color="gray")
                fig_cycle.add_hline(y=0, line_dash="dash", line_color="gray")
                fig_cycle.update_traces(textposition='top center')
                fig_cycle.update_layout(showlegend=False, height=600)
                st.plotly_chart(fig_cycle, use_container_width=True)
                
                st.info("""
                **宏观四象限解读**
                
                * **右上 (红色区) - 过热 (Overheating)**：增长强、通胀高。美联储通常会**加息**降温。
                    * *策略*：现金为王或做空债券，谨慎做多股票（估值受压）。
                * **左上 (红色区) - 滞胀 (Stagflation)**：增长弱、通胀高。最痛苦的阶段。
                    * *策略*：持有大宗商品 (黄金/原油) 抗通胀，现金为王，回避股债。
                * **左下 (绿色区) - 衰退 (Recession)**：增长弱、通胀低。美联储通常会**降息**救市。
                    * *策略*：债券是大牛市，股票在衰退末期开始反弹（分母端受益）。
                * **右下 (绿色区) - 复苏 (Recovery/Goldilocks)**：增长强、通胀低。经济最好的时光。
                    * *策略*：全力做多股票 (成长股/科技股)，享受戴维斯双击。
                """)
                
            except KeyError:
                st.error("数据不足。")

        # Tab 3: 热力图
        with tab3:
            col_h1, col_h2, col_h3 = st.columns([2, 1, 1])
            with col_h1:
                st.markdown("##### 跨资产/指标 强弱热力图 (动态区间标准化)")
            
            with col_h2:
                heatmap_years = st.slider("⏱️ 观察窗口 (年)", 1, 15, 3, key="heatmap_slider", help="选择几年，就用这几年的数据来计算相对强弱")
            
            with col_h3:
                hide_incomplete = st.checkbox("隐藏不全月份", value=True)

            mom_cols = [c for c in quant_df.columns if c.endswith("_Momentum")]
            
            if mom_cols:
                months_to_show_heat = heatmap_years * 12
                heatmap_raw = quant_df[mom_cols].tail(months_to_show_heat)
                
                if hide_incomplete:
                    if heatmap_raw.iloc[-1].isna().sum() > len(mom_cols) / 2:
                        heatmap_raw = heatmap_raw.iloc[:-1]

                heatmap_z = (heatmap_raw - heatmap_raw.mean()) / heatmap_raw.std()
                
                heatmap_data = heatmap_z.T
                x_labels = pd.to_datetime(heatmap_data.columns).strftime('%Y-%m')
                y_labels = heatmap_data.index.str.replace('_Momentum', '')
                
                fig_heat = px.imshow(
                    heatmap_data,
                    x=x_labels,
                    y=y_labels,
                    aspect="auto",
                    color_continuous_scale="RdBu_r", 
                    origin='lower',
                    zmin=-3, zmax=3
                )
                st.plotly_chart(fig_heat, use_container_width=True)
                
                st.success(f"""
                **💡 热力图极性与颜色解读：**
                
                本图使用了动态标准化计算，展示各指标在选定时间段内的相对强弱。
                
                * 🔴 **红色 (暖色系)** = **经济扩张/强劲 (Expansion)**
                    * **就业**：新增人数多，失业率低。
                    * **消费/增长**：需求旺盛，订单增加。
                    * **通胀**：物价上涨 (注：虽然高通胀不一定是好事，但代表经济活动热度高)。
                
                * 🔵 **蓝色 (冷色系)** = **经济收缩/疲软 (Contraction)**
                    * **就业**：裁员增加，失业率上升 (我们已对失业率做了反向处理，数值升高会变蓝)。
                    * **消费/增长**：需求萎缩，经济降温。
                    * **通胀**：通缩或低通胀。
                """)

               # Tab 4: 经济状态雷达 
        with tab4:
            st.markdown("##### 经济状态雷达：当前 vs 1年前 (基于历史百分位)")
            
            # 1. 准备雷达图数据
            # 选取每个板块的一个代表性指标
            radar_indicators = {
                "就业 (非农)": "非农就业人数 (Non-Farm Payrolls)",
                "消费 (零售)": "零售销售 (Retail Sales)",
                "增长 (工业)": "工业产出 (Industrial Production)",
                "通胀 (CPI)": "CPI (All Urban)",
                "信心 (密歇根)": "消费者信心 (UMich Sentiment)"
            }
            
            radar_data = {}
            # 计算历史分位数 
            for label, col_name in radar_indicators.items():
                if f"{col_name}_Raw" in quant_df.columns:
                    series = quant_df[f"{col_name}_Raw"].dropna()
                    
                    if not series.empty:
                        # 针对反向指标 (失业率等)，如果要加入，需要反转排名
                        # 目前选取的全都是正向指标 (越大越好)，所以直接计算
                        
                        # 计算当前值的百分位
                        current_val = series.iloc[-1]
                        current_rank = (series < current_val).mean() * 100
                        
                        # 计算1年前值的百分位
                        if len(series) > 12:
                            last_year_val = series.iloc[-13]
                            last_year_rank = (series < last_year_val).mean() * 100
                        else:
                            last_year_rank = 50 
                            
                        radar_data[label] = (current_rank, last_year_rank)

            if radar_data:
                categories = list(radar_data.keys())
                current_vals = [v[0] for v in radar_data.values()]
                last_year_vals = [v[1] for v in radar_data.values()]
                
                # 闭合雷达图
                categories.append(categories[0])
                current_vals.append(current_vals[0])
                last_year_vals.append(last_year_vals[0])

                fig_radar = go.Figure()
                
                # 绘制当前状态 (红色)
                fig_radar.add_trace(go.Scatterpolar(
                    r=current_vals, theta=categories,
                    fill='toself', name='当前 (Current)',
                    line_color='red',
                    customdata=last_year_vals,
                    hovertemplate="<b>%{theta}</b><br>当前: %{r:.1f}<br>1年前: %{customdata:.1f}<extra></extra>"
                ))
                
                # 绘制1年前状态 (灰色)
                fig_radar.add_trace(go.Scatterpolar(
                    r=last_year_vals, theta=categories,
                    fill='toself', name='1年前 (1 Year Ago)',
                    line_color='gray', opacity=0.5,
                    customdata=current_vals,
                    hovertemplate="<b>%{theta}</b><br>1年前: %{r:.1f}<br>当前: %{customdata:.1f}<extra></extra>"
                ))

                fig_radar.update_layout(
                    polar=dict(
                        radialaxis=dict(visible=True, range=[0, 100]),
                    ),
                    showlegend=True,
                    height=500,
                    title=" (0=历史最冷, 100=历史最热)"
                )
                
                st.plotly_chart(fig_radar, use_container_width=True)
                
                st.info("""
                **💡 雷达图解读**：
                * **维度**：选取了五大核心领域的代表性指标。
                * **数值 (0-100)**：代表**历史百分位**。
                    * **100**：表示当前数据处于所选历史区间内的**最高点**（极度过热/强劲）。
                    * **50**：表示处于历史**中位数**（正常水平）。
                    * **0**：表示处于历史**最低点**（极度衰退/冰点）。
                * **对比**：红色覆盖区域 > 灰色区域，说明当前经济比一年前更热/更强。
                """)
        
        # 5. 原始数据表格
        st.markdown("---")
        st.subheader("📋 原始数据明细 (Raw Data)")
        with st.expander("点击展开/收起 完整数据表格", expanded=False):
            st.caption("以下表格展示了所有指标的原始数值（未经处理）。数据已按日期降序排列。**注意：GDP 等季度指标在非发布月份显示为空 (`-`) 是正常的，请参考季度发布月份 (1/4/7/10月)。**")
            
            display_df = raw_df.sort_index(ascending=False).copy()
            display_df.index = display_df.index.strftime('%Y-%m-%d')
            
            st.dataframe(
                display_df.fillna("-"),
                use_container_width=True,
                height=500
            )
            
            csv = display_df.to_csv().encode('utf-8')
            st.download_button(
                label="📥 下载 CSV 数据文件",
                data=csv,
                file_name=f'us_macro_data_{datetime.now().strftime("%Y%m%d")}.csv',
                mime='text/csv',
            )
    else:
        st.error("数据获取失败。")
else:
    st.error("API Key 未配置。")
