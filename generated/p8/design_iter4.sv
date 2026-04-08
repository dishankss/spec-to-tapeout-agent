module fp16_multiplier(
  input  logic [15:0] a,
  input  logic [15:0] b,
  output logic [15:0] result
);

  logic        sign_a, sign_b, sign_res;
  logic [4:0]  exp_a, exp_b;
  logic [9:0]  frac_a, frac_b;

  logic        a_is_zero, b_is_zero;
  logic        a_is_sub,  b_is_sub;
  logic        a_is_inf,  b_is_inf;
  logic        a_is_nan,  b_is_nan;

  logic [10:0] sig_a, sig_b;
  logic [21:0] prod;
  logic [21:0] norm_prod;
  logic [21:0] sub_prod;

  integer exp_a_unb, exp_b_unb;
  integer exp_sum, norm_exp;
  integer shift_amt, sub_shift;
  integer i;

  logic found;
  logic lost_sticky;
  logic sticky_extra;
  logic guard_bit, round_bit, sticky_bit;
  logic round_inc;

  logic [10:0] frac_keep_sub;
  logic [11:0] sig_keep_norm;
  logic [11:0] sig_round_norm;
  logic [10:0] frac_round_sub;

  logic [4:0]  exp_out;
  logic [9:0]  frac_out;

  always_comb begin
    sign_a = a[15];
    sign_b = b[15];
    exp_a  = a[14:10];
    exp_b  = b[14:10];
    frac_a = a[9:0];
    frac_b = b[9:0];

    sign_res = sign_a ^ sign_b;

    a_is_zero = (exp_a == 5'd0)  && (frac_a == 10'd0);
    b_is_zero = (exp_b == 5'd0)  && (frac_b == 10'd0);
    a_is_sub  = (exp_a == 5'd0)  && (frac_a != 10'd0);
    b_is_sub  = (exp_b == 5'd0)  && (frac_b != 10'd0);
    a_is_inf  = (exp_a == 5'h1F) && (frac_a == 10'd0);
    b_is_inf  = (exp_b == 5'h1F) && (frac_b == 10'd0);
    a_is_nan  = (exp_a == 5'h1F) && (frac_a != 10'd0);
    b_is_nan  = (exp_b == 5'h1F) && (frac_b != 10'd0);

    sig_a = a_is_sub ? {1'b0, frac_a} : {1'b1, frac_a};
    sig_b = b_is_sub ? {1'b0, frac_b} : {1'b1, frac_b};
    prod  = sig_a * sig_b;

    exp_a_unb = a_is_sub ? -14 : (exp_a - 15);
    exp_b_unb = b_is_sub ? -14 : (exp_b - 15);
    exp_sum   = exp_a_unb + exp_b_unb;

    norm_prod    = 22'd0;
    sub_prod     = 22'd0;
    norm_exp     = 0;
    shift_amt    = 0;
    sub_shift    = 0;
    found        = 1'b0;
    lost_sticky  = 1'b0;
    sticky_extra = 1'b0;
    guard_bit    = 1'b0;
    round_bit    = 1'b0;
    sticky_bit   = 1'b0;
    round_inc    = 1'b0;
    frac_keep_sub  = 11'd0;
    sig_keep_norm  = 12'd0;
    sig_round_norm = 12'd0;
    frac_round_sub = 11'd0;
    exp_out      = 5'd0;
    frac_out     = 10'd0;
    result       = 16'd0;

    if (a_is_nan || b_is_nan) begin
      result = 16'h7E00;
    end else if ((a_is_inf && b_is_zero) || (b_is_inf && a_is_zero)) begin
      result = 16'h7E00;
    end else if (a_is_inf || b_is_inf) begin
      result = {sign_res, 5'h1F, 10'd0};
    end else if (a_is_zero || b_is_zero) begin
      result = {sign_res, 5'd0, 10'd0};
    end else begin
      norm_exp = exp_sum;

      if (prod[21]) begin
        norm_prod   = prod >> 1;
        norm_exp    = exp_sum + 1;
        lost_sticky = prod[0];
      end else begin
        for (i = 20; i >= 0; i = i - 1) begin
          if (!found && prod[i]) begin
            shift_amt = 20 - i;
            found     = 1'b1;
          end
        end
        norm_prod = prod << shift_amt;
        norm_exp  = exp_sum - shift_amt;
      end

      if (norm_exp > 15) begin
        result = {sign_res, 5'h1F, 10'd0};
      end else if (norm_exp >= -14) begin
        sig_keep_norm = {1'b0, norm_prod[20:10]};
        guard_bit     = norm_prod[9];
        round_bit     = norm_prod[8];
        sticky_bit    = (|norm_prod[7:0]) | lost_sticky;
        round_inc     = guard_bit && (round_bit || sticky_bit || sig_keep_norm[0]);

        sig_round_norm = sig_keep_norm + {11'd0, round_inc};

        if (sig_round_norm[11]) begin
          if (norm_exp + 1 > 15) begin
            result = {sign_res, 5'h1F, 10'd0};
          end else begin
            exp_out  = norm_exp + 16;
            frac_out = 10'd0;
            result   = {sign_res, exp_out, frac_out};
          end
        end else begin
          exp_out  = norm_exp + 15;
          frac_out = sig_round_norm[9:0];
          result   = {sign_res, exp_out, frac_out};
        end
      end else begin
        sub_shift = -14 - norm_exp;
        if (sub_shift >= 22) begin
          sub_prod = 22'd0;
        end else begin
          sub_prod = norm_prod >> sub_shift;
        end

        sticky_extra = lost_sticky;
        for (i = 0; i < 22; i = i + 1) begin
          if (i < sub_shift) begin
            sticky_extra = sticky_extra | norm_prod[i];
          end
        end

        frac_keep_sub = {1'b0, sub_prod[19:10]};
        guard_bit     = sub_prod[9];
        round_bit     = sub_prod[8];
        sticky_bit    = (|sub_prod[7:0]) | sticky_extra;
        round_inc     = guard_bit && (round_bit || sticky_bit || frac_keep_sub[0]);

        frac_round_sub = frac_keep_sub + {10'd0, round_inc};

        if (frac_round_sub[10]) begin
          result = {sign_res, 5'd1, 10'd0};
        end else begin
          result = {sign_res, 5'd0, frac_round_sub[9:0]};
        end
      end
    end
  end

endmodule
