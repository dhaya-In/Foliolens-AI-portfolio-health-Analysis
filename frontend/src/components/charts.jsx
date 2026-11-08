import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend } from 'recharts'

export const PALETTE = ['#1d4ed8', '#0891b2', '#7c3aed', '#059669', '#d97706', '#db2777', '#475569', '#65a30d', '#0d9488', '#9333ea']

export function AllocationPie({ data, height = 260, valueSuffix = '%' }) {
  if (!data?.length) return <p className="muted small">No allocation data.</p>
  return (
    <div style={{ width: '100%', height }} role="img"
         aria-label={'Allocation: ' + data.map(d => `${d.name} ${d.value}${valueSuffix}`).join(', ')}>
      <ResponsiveContainer>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="85%" paddingAngle={1} isAnimationActive={false}>
            {data.map((d, i) => <Cell key={d.name} fill={d.name === 'Unknown' ? '#cbd5e1' : PALETTE[i % PALETTE.length]} />)}
          </Pie>
          <Tooltip formatter={(v) => `${v}${valueSuffix}`} />
          <Legend layout="vertical" align="right" verticalAlign="middle" iconSize={9} wrapperStyle={{ fontSize: 12.5 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  )
}
