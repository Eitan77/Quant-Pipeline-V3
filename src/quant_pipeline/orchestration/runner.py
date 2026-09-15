from collections import deque
class DagRunner:
    def __init__(self,*,stages,dependencies):self.stages=stages;self.dependencies=dependencies
    def ordered_stages(self,requested=None):
        wanted=set(requested or self.stages); changed=True
        while changed:
            changed=False
            for s in tuple(wanted):
                for d in self.dependencies.get(s,()):
                    if d not in wanted:wanted.add(d);changed=True
        degree={x:0 for x in wanted}; children={x:[] for x in wanted}
        for x in wanted:
            for d in self.dependencies.get(x,()):
                if d in wanted:degree[x]+=1;children[d].append(x)
        q=deque(sorted(x for x,n in degree.items() if n==0));out=[]
        while q:
            x=q.popleft();out.append(x)
            for c in sorted(children[x]):
                degree[c]-=1
                if not degree[c]:q.append(c)
        if len(out)!=len(wanted):raise RuntimeError("Pipeline stage graph contains a cycle")
        return out
    def run(self,ctx,requested=None):
        out=[]
        for name in self.ordered_stages(requested):ctx.telemetry.event("stage_start",stage=name); result=self.stages[name].run(ctx);ctx.telemetry.event("stage_complete",stage=name,metrics=dict(result.metrics));out.append(result)
        return out

