using ApexVoid.CTraderFeed;

namespace CTraderFeed.Tests;

public sealed class ClosedBarEmitterTests
{
  [Fact]
  public void LiveBarIsEmittedOnceOnlyAfterNextPeriodBegins()
  {
    var emitter = new ClosedBarEmitter();
    var forming = new OhlcBar(1_000, 10, 11, 9, 10, 1);
    var updated = forming with { Close = 10.5m };
    var nextPeriod = new OhlcBar(1_300, 10.5m, 12, 10, 11, 2);

    Assert.Empty(emitter.Observe("M5", forming));
    Assert.Empty(emitter.Observe("M5", updated));

    var emitted = emitter.Observe("M5", nextPeriod);

    Assert.Single(emitted);
    Assert.Equal(updated, emitted[0]);
    Assert.Empty(emitter.Observe("M5", updated));
    Assert.Empty(emitter.Observe("M5", nextPeriod with { Close = 11.5m }));
  }
}
