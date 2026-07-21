using ApexVoid.CTraderFeed;

namespace CTraderFeed.Tests;

public sealed class VolumePlannerTests
{
  private static readonly SymbolInfo Symbol = new(
    "XAU",
    "XAUUSD",
    7,
    Digits: 2,
    PipPosition: 1,
    MinVolume: 100,
    StepVolume: 100,
    MaxVolume: 100_000,
    LotSize: 10_000
  );

  [Theory]
  [InlineData(875.21, 0.02, 200)]
  [InlineData(2000, 0.06, 600)]
  public void SizesFromRiskAndFloorsToBrokerStep(
    double balance,
    double expectedLots,
    long expectedVolume
  )
  {
    var result = Size(Convert.ToDecimal(balance));

    Assert.Equal(Convert.ToDecimal(expectedLots), result.Lots);
    Assert.Equal(expectedVolume, result.Volume);
    Assert.Equal(65m, result.StopPips);
    var impliedRisk = result.Lots * result.StopPips * 10m;
    Assert.True(impliedRisk <= Convert.ToDecimal(balance) * 0.02m);
  }

  [Fact]
  public void BelowMinimumRejectsWithArithmetic()
  {
    var error = Assert.Throws<VolumePlanningException>(() => Size(300m));

    Assert.Contains("balance 300.00 × 2% = $6.00", error.Message);
    Assert.Contains("0.009 lots", error.Message);
    Assert.Contains("below the 0.01 minimum", error.Message);
  }

  [Fact]
  public void MaximumLotsCapsRunawayBalance()
  {
    var result = Size(decimal.MaxValue);

    Assert.Equal(1m, result.Lots);
    Assert.Equal(10_000, result.Volume);
  }

  [Fact]
  public void FiveTargetFeasibilityRejectsTwoStepsWithComputedRemedy()
  {
    var sizing = Size(875.21m);

    var error = Assert.Throws<VolumePlanningException>(() =>
      VolumePlanner.EnsureTargetFeasibility(
        sizing,
        875.21m,
        2m,
        10m,
        5,
        Symbol
      )
    );

    Assert.Contains("0.02 lots = 2 steps; 5 targets need 5", error.Message);
    Assert.Contains("balance ≥ $1,625", error.Message);
    Assert.Contains("stop ≤ 30 pips", error.Message);
  }

  [Fact]
  public void FiveStepsSplitIntoOneStepPerTarget()
  {
    var sizing = Size(1_625m);
    VolumePlanner.EnsureTargetFeasibility(
      sizing,
      1_625m,
      2m,
      10m,
      5,
      Symbol
    );

    Assert.Equal(
      new long[] { 100, 100, 100, 100, 100 },
      VolumePlanner.SplitWeighted(
        sizing.Volume,
        Symbol,
        [20, 20, 20, 20, 20]
      )
    );
  }

  [Fact]
  public void WeightedLargestRemainderProducesExactSteps()
  {
    Assert.Equal(
      new long[] { 500, 500, 600, 400 },
      VolumePlanner.SplitWeighted(2_000, Symbol, [25, 25, 30, 20])
    );
  }

  [Fact]
  public void RoundingProneWeightsStayWithinOneStepAndSumExactly()
  {
    var weights = new[] { 17, 19, 23, 41 };
    var slices = VolumePlanner.SplitWeighted(2_300, Symbol, weights);

    Assert.Equal(2_300, slices.Sum());
    for (var index = 0; index < weights.Length; index++)
    {
      var actualSteps = (decimal)slices[index] / Symbol.StepVolume;
      var idealSteps = 23m * weights[index] / weights.Sum();
      Assert.True(Math.Abs(actualSteps - idealSteps) <= 1m);
    }
  }

  private static RiskSizingResult Size(decimal balance) =>
    VolumePlanner.SizeForRisk(
      balance,
      riskPercent: 2m,
      stopDistance: 6.5m,
      pipValuePerLot: 10m,
      maxLots: 1m,
      Symbol
    );
}
