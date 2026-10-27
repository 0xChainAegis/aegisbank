interface Props {
  disabled: boolean;
  onPrepare: (instruction: string) => void;
}

const tasks = [
  { title: '查本月账单', instruction: '分析我的本月账单',
    description: '查看消费分类和异常提示，只查询，不改变账户。' },
  { title: '转账880元', instruction: '向 ACC-2002 转账 880 元',
    description: '核对收款方和金额。计划待确认时，钱还没有转出。' },
  { title: '挂失模拟卡片', instruction: '挂失我的卡片 CARD-8821',
    description: '核对卡号，体验高风险操作的确认和演示身份验证。' },
];

export default function TrialGuide({ disabled, onPrepare }: Props) {
  return (
    <section className="card trial-guide" aria-labelledby="trial-heading">
      <h2 id="trial-heading">第一次使用，从这三项开始</h2>
      <p>选择任务会填入指令，请检查内容后再提交；涉及修改的操作仍需确认。</p>
      <div className="trial-grid">
        {tasks.map((task, index) => (
          <article key={task.title}>
            <span className="eyebrow">0{index + 1}</span>
            <h3>{task.title}</h3>
            <p>{task.description}</p>
            <button className="ghost-button" disabled={disabled}
              onClick={() => onPrepare(task.instruction)}>填入{task.title}任务</button>
          </article>
        ))}
      </div>
    </section>
  );
}
