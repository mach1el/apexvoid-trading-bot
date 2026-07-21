using ApexVoid.CTraderFeed;

namespace CTraderFeed.Tests;

public sealed class StopTrailPlannerTests
{
  private static readonly SymbolInfo Symbol = new(
    "XAU",
    "XAUUSD",
    7,
    Digits: 2,
    PipPosition: 1
  );

  [Theory]
  [InlineData(TradeDirection.Buy, 4000.5, 4003.2, 4006.2, 4009.2)]
  [InlineData(TradeDirection.Sell, 3999.9, 3997.2, 3994.2, 3991.2)]
  public void TrailsAcrossFourPartialTargetsInDirection(
    TradeDirection direction,
    double afterTp1,
    double afterTp2,
    double afterTp3,
    double afterTp4
  )
  {
    var state = State(direction);
    var expected = new[] { afterTp1, afterTp2, afterTp3, afterTp4 };

    for (var index = 0; index < expected.Length; index++)
    {
      var move = Assert.IsType<StopTrailMove>(
        StopTrailPlanner.Plan(state, index, Symbol, 3)
      );
      Assert.Equal(Convert.ToDecimal(expected[index]), move.StopLoss);
      state = state with { CurrentStopLoss = move.StopLoss };
    }
    Assert.Null(StopTrailPlanner.Plan(state, 4, Symbol, 3));
  }

  [Theory]
  [InlineData(TradeDirection.Buy, 4004.0)]
  [InlineData(TradeDirection.Sell, 3996.0)]
  public void IgnoresStopThatWouldMoveBackward(
    TradeDirection direction,
    double currentStop
  )
  {
    var state = State(direction) with
    {
      CurrentStopLoss = Convert.ToDecimal(currentStop),
    };

    Assert.Null(StopTrailPlanner.Plan(state, 0, Symbol, 3));
  }

  private static AutoTradePositionState State(TradeDirection direction) => new(
    "candidate",
    91,
    7,
    direction,
    4000.2m,
    1_000,
    1_000,
    [200, 200, 200, 200, 200],
    [30, 60, 90, 120, 200],
    0,
    1_000,
    direction == TradeDirection.Buy ? 3993.7m : 4006.7m
  );
}
