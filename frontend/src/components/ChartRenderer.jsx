import React, { useState } from 'react'
import ReactECharts from 'echarts-for-react'

function mergeTheme(option) {
  return {
    backgroundColor: 'transparent',
    textStyle: { color: '#e2e8f0' },
    ...option,
    xAxis: option.xAxis
      ? {
          axisLabel: { color: '#94a3b8' },
          axisLine: { lineStyle: { color: '#2a2d3e' } },
          splitLine: { lineStyle: { color: '#2a2d3e' } },
          ...option.xAxis,
        }
      : undefined,
    yAxis: option.yAxis
      ? {
          axisLabel: { color: '#94a3b8' },
          axisLine: { lineStyle: { color: '#2a2d3e' } },
          splitLine: { lineStyle: { color: '#2a2d3e', type: 'dashed' } },
          ...option.yAxis,
        }
      : undefined,
    legend: option.legend
      ? { textStyle: { color: '#e2e8f0' }, ...option.legend }
      : undefined,
    tooltip: option.tooltip
      ? { backgroundColor: '#1a1d27', borderColor: '#2a2d3e', textStyle: { color: '#e2e8f0' }, ...option.tooltip }
      : undefined,
  }
}

export default function ChartRenderer({ chartData, title, chartId, height = 260 }) {
  const [error, setError] = useState(false)

  if (!chartData) return null

  if (error) {
    return (
      <div className="chart-container chart-container--error">
        <span>图表渲染失败</span>
      </div>
    )
  }

  return (
    <div className="chart-container">
      {title && <div className="chart-container__title">{title}</div>}
      <ReactECharts
        key={chartId}
        option={mergeTheme(chartData)}
        style={{ height: `${height}px`, width: '100%' }}
        notMerge
        lazyUpdate
        onEvents={{ error: () => setError(true) }}
      />
    </div>
  )
}
